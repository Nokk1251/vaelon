// Live voice: a real-time spoken conversation through the core's local bridge (see src/vaelon/live.py).
// The page sends 16 kHz microphone audio to ws://127.0.0.1:<port> and plays the 24 kHz voice that comes back.
// The bridge - not this page - holds the Gemini key and talks to Google. While Live is on, your microphone audio
// (and, with screen sharing on, pictures of your screen) go to Google.

import type { MadeFile } from "./vaelonApi";

export type LiveHandle = {
  stop(): void;
  /** Screen sharing on/off (the core takes the pictures). */
  setScreen(on: boolean): void;
  setMuted(on: boolean): void;
  /** Stop talking now and cancel what is being worked on. */
  interrupt(): void;
  /** Unlock audio (needs a click in a window opened by a script). True when it runs. */
  resume(): Promise<boolean>;
  /** Loudness of the voice being played, 0..1. */
  level(): number;
  speaking(): boolean;
};

export type LiveEvents = {
  onReady?: (model: string) => void;
  onYou?: (text: string) => void; // a piece of what you said (transcript)
  onSay?: (text: string) => void; // a piece of what is being said back
  onTurn?: () => void; // the answer is complete
  onInterrupted?: () => void;
  onTask?: (text: string) => void; // Vaelon started real work for this request
  onTool?: (name: string) => void;
  onTaskDone?: () => void;
  onApproval?: (job: string, summary: string, card: string) => void;
  onFiles?: (files: MadeFile[]) => void;
  onMicLevel?: (level: number) => void;
  onError?: (message: string) => void;
  onClose?: () => void;
};

const IN_RATE = 16000;
const OUT_RATE = 24000;

/** HMAC-SHA256(key, purpose|nonce) as hex - how the page and the bridge prove they know the access key without
 *  ever sending it (something else could be listening on the bridge's port). */
async function proof(key: string, purpose: string, nonce: string): Promise<string> {
  const enc = new TextEncoder();
  const k = await crypto.subtle.importKey("raw", enc.encode(key), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = new Uint8Array(await crypto.subtle.sign("HMAC", k, enc.encode(`${purpose}|${nonce}`)));
  return Array.from(sig, (b) => b.toString(16).padStart(2, "0")).join("");
}

function newNonce(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
}

export async function startLive(opts: { port: number; token: string; screen: boolean } & LiveEvents): Promise<LiveHandle | null> {
  if (!navigator.mediaDevices?.getUserMedia) {
    opts.onError?.("This window cannot use the microphone.");
    return null;
  }
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    });
  } catch {
    opts.onError?.("Microphone access was blocked. Allow it in Windows Settings > Privacy & security > Microphone.");
    return null;
  }
  const ctx = new AudioContext();
  const src = ctx.createMediaStreamSource(stream);
  const proc = ctx.createScriptProcessor(2048, 1, 1);
  const silent = ctx.createGain();
  silent.gain.value = 0;
  const out = ctx.createGain();
  const meter = ctx.createAnalyser();
  meter.fftSize = 512;
  const probe = new Float32Array(new ArrayBuffer(meter.fftSize * 4));
  out.connect(meter);
  out.connect(ctx.destination);

  let muted = false;
  let stopped = false;
  let open = false;
  let nextTime = 0;
  const playing = new Set<AudioBufferSourceNode>();
  const ws = new WebSocket(`ws://127.0.0.1:${opts.port}`);
  ws.binaryType = "arraybuffer";

  const flush = () => {
    for (const s of playing) {
      try {
        s.stop();
      } catch {
        /* already ended */
      }
    }
    playing.clear();
    nextTime = 0;
  };

  const play = (buf: ArrayBuffer) => {
    const pcm = new Int16Array(buf);
    if (!pcm.length) return;
    const audio = ctx.createBuffer(1, pcm.length, OUT_RATE);
    const ch = audio.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 32768;
    const node = ctx.createBufferSource();
    node.buffer = audio;
    node.connect(out);
    const at = Math.max(ctx.currentTime + 0.03, nextTime);
    node.start(at);
    nextTime = at + audio.duration;
    playing.add(node);
    node.onended = () => playing.delete(node);
  };

  const hello = newNonce();
  ws.onopen = () => {
    ws.send(JSON.stringify({ hello, screen: opts.screen }));
  };
  ws.onmessage = async (e) => {
    if (!open) {
      // first message must be the bridge's proof; nothing (no audio, no key) goes out before it checks out
      let c: { type?: string; proof?: string; nonce?: string } = {};
      try {
        c = JSON.parse(String(e.data));
      } catch {
        /* not a challenge */
      }
      const fine = c.type === "challenge" && typeof c.nonce === "string"
        && c.proof === (await proof(opts.token, "vaelon-live-server", hello));
      if (!fine) {
        opts.onError?.("The live bridge could not prove it is Vaelon. Restart Vaelon.");
        ws.close(1000);
        return;
      }
      ws.send(JSON.stringify({ proof: await proof(opts.token, "vaelon-live-client", c.nonce!) }));
      open = true;
      return;
    }
    if (e.data instanceof ArrayBuffer) return play(e.data);
    let m: { type?: string; text?: string; model?: string; name?: string; job?: string; summary?: string; card?: string;
      files?: MadeFile[] };
    try {
      m = JSON.parse(String(e.data));
    } catch {
      return;
    }
    if (m.type === "ready") opts.onReady?.(m.model ?? "");
    else if (m.type === "you") opts.onYou?.(m.text ?? "");
    else if (m.type === "say") opts.onSay?.(m.text ?? "");
    else if (m.type === "turn") opts.onTurn?.();
    else if (m.type === "interrupted") {
      flush(); // you spoke over it: drop what was still queued
      opts.onInterrupted?.();
    } else if (m.type === "task") opts.onTask?.(m.text ?? "");
    else if (m.type === "tool") opts.onTool?.(m.name ?? "");
    else if (m.type === "task_done") opts.onTaskDone?.();
    else if (m.type === "approval") opts.onApproval?.(m.job ?? "", m.summary ?? "", m.card ?? "");
    else if (m.type === "files") opts.onFiles?.(m.files ?? []);
    else if (m.type === "error") opts.onError?.(m.text ?? "Live stopped.");
  };
  ws.onerror = () => opts.onError?.("Cannot reach the live bridge. Restart Vaelon.");
  ws.onclose = (e) => {
    open = false;
    if (!stopped) {
      if (e.code === 4401) opts.onError?.("The access key was rejected.");
      release(); // the bridge went away: the microphone and the audio engine must not stay open
      opts.onClose?.();
    }
  };

  proc.onaudioprocess = (e) => {
    if (stopped) return;
    const data = e.inputBuffer.getChannelData(0);
    let sum = 0;
    for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
    opts.onMicLevel?.(muted ? 0 : Math.min(1, Math.sqrt(sum / data.length) * 6));
    if (!open || muted || ws.readyState !== WebSocket.OPEN) return;
    // down to 16 kHz, 16-bit: each output sample is the average of its window
    const ratio = ctx.sampleRate / IN_RATE;
    const n = Math.floor(data.length / ratio);
    const pcm = new Int16Array(n);
    for (let i = 0; i < n; i++) {
      const a = Math.floor(i * ratio);
      const b = Math.min(data.length, Math.floor((i + 1) * ratio));
      let acc = 0;
      for (let j = a; j < b; j++) acc += data[j];
      const v = Math.max(-1, Math.min(1, acc / Math.max(1, b - a)));
      pcm[i] = v < 0 ? v * 0x8000 : v * 0x7fff;
    }
    ws.send(pcm.buffer);
  };
  src.connect(proc);
  proc.connect(silent).connect(ctx.destination);

  const sendJson = (obj: unknown) => {
    if (open && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj)); // never before the handshake
  };

  function release() {
    if (stopped) return;
    stopped = true;
    flush();
    proc.disconnect();
    src.disconnect();
    stream.getTracks().forEach((t) => t.stop());
    try {
      ws.close(1000);
    } catch {
      /* not open */
    }
    void ctx.close();
    opts.onMicLevel?.(0);
  }

  return {
    stop() {
      release();
    },
    setScreen(on) {
      sendJson({ screen: on });
    },
    setMuted(on) {
      muted = on;
    },
    interrupt() {
      flush();
      sendJson({ stop: true });
    },
    async resume() {
      if (ctx.state !== "running") {
        await Promise.race([ctx.resume().catch(() => undefined), new Promise((r) => setTimeout(r, 700))]);
      }
      return ctx.state === "running";
    },
    level() {
      if (nextTime <= ctx.currentTime) return 0;
      meter.getFloatTimeDomainData(probe);
      let sum = 0;
      for (let i = 0; i < probe.length; i++) sum += probe[i] * probe[i];
      return Math.min(1, Math.sqrt(sum / probe.length) * 4.5);
    },
    speaking() {
      return nextTime > ctx.currentTime + 0.02;
    },
  };
}
