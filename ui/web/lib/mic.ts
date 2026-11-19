// Microphone: records one spoken command as plain 16 kHz WAV and stops by itself ~1.4 s after you finish talking
// (or after 30 s). WAV needs no decoder anywhere, so local Whisper and Groq both read it directly.
// Audio stays in memory and goes only to Vaelon's local core (/stt); nothing is saved.

export type MicHandle = { stop(): void };

const RATE = 16000;

function toWav(chunks: Float32Array[], inRate: number): Blob {
  const total = chunks.reduce((n, c) => n + c.length, 0);
  const ratio = inRate / RATE;
  const outLen = Math.floor(total / ratio);
  const pcm = new Int16Array(outLen);
  // flatten + simple downsample (average of each window)
  const flat = new Float32Array(total);
  let off = 0;
  for (const c of chunks) {
    flat.set(c, off);
    off += c.length;
  }
  for (let i = 0; i < outLen; i++) {
    const a = Math.floor(i * ratio);
    const b = Math.min(total, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = a; j < b; j++) sum += flat[j];
    const v = Math.max(-1, Math.min(1, sum / Math.max(1, b - a)));
    pcm[i] = v < 0 ? v * 0x8000 : v * 0x7fff;
  }
  const buf = new ArrayBuffer(44 + pcm.byteLength);
  const dv = new DataView(buf);
  const str = (o: number, s: string) => [...s].forEach((ch, i) => dv.setUint8(o + i, ch.charCodeAt(0)));
  str(0, "RIFF");
  dv.setUint32(4, 36 + pcm.byteLength, true);
  str(8, "WAVE");
  str(12, "fmt ");
  dv.setUint32(16, 16, true);
  dv.setUint16(20, 1, true); // PCM
  dv.setUint16(22, 1, true); // mono
  dv.setUint32(24, RATE, true);
  dv.setUint32(28, RATE * 2, true);
  dv.setUint16(32, 2, true);
  dv.setUint16(34, 16, true);
  str(36, "data");
  dv.setUint32(40, pcm.byteLength, true);
  new Int16Array(buf, 44).set(pcm);
  return new Blob([buf], { type: "audio/wav" });
}

export async function recordCommand(opts: {
  onLevel?: (level: number) => void;
  onDone: (blob: Blob, mime: string) => void;
  onError: (msg: string) => void;
}): Promise<MicHandle | null> {
  if (!navigator.mediaDevices?.getUserMedia) {
    opts.onError("This window cannot use the microphone.");
    return null;
  }
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
    });
  } catch {
    opts.onError("Microphone access was blocked. Allow it in Windows Settings > Privacy & security > Microphone.");
    return null;
  }
  const ctx = new AudioContext();
  const src = ctx.createMediaStreamSource(stream);
  // ScriptProcessor is old but works everywhere (incl. the desktop app's WebView2) without extra files
  const proc = ctx.createScriptProcessor(4096, 1, 1);
  const mute = ctx.createGain();
  mute.gain.value = 0;
  const chunks: Float32Array[] = [];
  let spoke = false;
  let quietSince = performance.now();
  const started = performance.now();
  let stopped = false;

  const finish = () => {
    if (stopped) return;
    stopped = true;
    proc.disconnect();
    src.disconnect();
    stream.getTracks().forEach((t) => t.stop());
    const rate = ctx.sampleRate;
    void ctx.close();
    opts.onLevel?.(0);
    if (!spoke || chunks.length < 3) {
      opts.onError("I did not hear anything.");
      return;
    }
    opts.onDone(toWav(chunks, rate), "audio/wav");
  };

  proc.onaudioprocess = (e) => {
    if (stopped) return;
    const data = new Float32Array(e.inputBuffer.getChannelData(0));
    chunks.push(data);
    let sum = 0;
    for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
    const level = Math.min(1, Math.sqrt(sum / data.length) * 6);
    opts.onLevel?.(level);
    const now = performance.now();
    if (level > 0.12) {
      spoke = true;
      quietSince = now;
    }
    if ((spoke && now - quietSince > 1400) || now - started > 30000 || (!spoke && now - started > 8000)) finish();
  };
  src.connect(proc);
  proc.connect(mute).connect(ctx.destination); // the processor only runs while connected; muted = no echo
  return { stop: finish };
}

/** Silence that ends a phrase, and the shorter pause after which transcription may already begin. */
export const ENDPOINT_MS = 700;
export const EARLY_MS = 300;

export type LoopHandle = {
  stop(): void;
  /** Unlock the audio engine (needs a click in a window opened by a script). Resolves to true when it runs. */
  resume(): Promise<boolean>;
};

/** Hands-free conversation: the microphone stays open and every phrase you say is cut out by itself
 *  (starts when you start talking, ends ~0.7 s after you stop) and handed over as 16 kHz WAV.
 *  `loud()` tells the loop that Vaelon is speaking right now: then a firmer, longer voice is needed to count as
 *  an interruption, so its own voice from the speakers does not trigger it (echo cancellation is on as well).
 *  Nothing is recorded to disk; audio that is not speech is thrown away at once. */
export async function listenLoop(opts: {
  onLevel?: (level: number) => void;
  onSpeech?: (talking: boolean) => void;
  /** `early`: `onEarly` already got this very phrase (nothing was said after it). */
  onUtterance: (wav: Blob, ms: number, overVaelon: boolean, early: boolean) => void;
  /** A short pause (EARLY_MS) inside a phrase: probably its end. Lets the caller start transcribing now instead
   *  of after the full ENDPOINT_MS of silence. Called again if you go on talking and pause once more. */
  onEarly?: (wav: Blob, ms: number) => void;
  onError: (msg: string) => void;
  loud?: () => boolean;
}): Promise<LoopHandle | null> {
  if (!navigator.mediaDevices?.getUserMedia) {
    opts.onError("This window cannot use the microphone.");
    return null;
  }
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    });
  } catch {
    opts.onError("Microphone access was blocked. Allow it in Windows Settings > Privacy & security > Microphone.");
    return null;
  }
  const ctx = new AudioContext();
  const src = ctx.createMediaStreamSource(stream);
  const proc = ctx.createScriptProcessor(2048, 1, 1);
  const mute = ctx.createGain();
  mute.gain.value = 0;
  const blockMs = (2048 / ctx.sampleRate) * 1000;
  const pre: Float32Array[] = []; // the last ~0.7 s before speech starts, so the first syllable is not cut off
  let chunks: Float32Array[] = [];
  let noise = 0.03; // the room's own noise level; the threshold follows it
  let talking = false;
  let hot = 0;
  let quiet = 0;
  let over = false;
  let stopped = false;
  let early = false; // onEarly was called for the pause we are in

  proc.onaudioprocess = (e) => {
    if (stopped) return;
    const data = new Float32Array(e.inputBuffer.getChannelData(0));
    let sum = 0;
    for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
    const level = Math.min(1, Math.sqrt(sum / data.length) * 6);
    opts.onLevel?.(level);
    const vaelon = !!opts.loud?.();
    const base = Math.max(0.1, Math.min(0.3, noise * 3));
    if (!talking) {
      pre.push(data);
      if (pre.length > 16) pre.shift(); // ~0.7 s: quiet first sounds (s, f, h) must not be lost
      const threshold = vaelon ? Math.max(0.3, base * 1.8) : base;
      if (level > threshold) hot++;
      else {
        hot = 0;
        if (!vaelon) noise += (level - noise) * 0.05;
      }
      if (hot >= (vaelon ? 6 : 3)) {
        talking = true;
        over = vaelon;
        early = false;
        chunks = pre.splice(0);
        quiet = 0;
        opts.onSpeech?.(true);
      }
      return;
    }
    chunks.push(data);
    if (level > base * 0.8) {
      quiet = 0;
      early = false; // you went on talking: what was handed over early is not the whole phrase
    } else quiet += blockMs;
    const total = chunks.length * blockMs;
    if (opts.onEarly && !early && quiet > EARLY_MS && quiet <= ENDPOINT_MS && total - quiet > 280) {
      early = true;
      opts.onEarly(toWav(chunks, ctx.sampleRate), total - quiet);
    }
    if (quiet > ENDPOINT_MS || total > 30000) {
      talking = false;
      hot = 0;
      opts.onSpeech?.(false);
      const voiced = total - quiet;
      const take = chunks;
      chunks = [];
      if (voiced > 280) opts.onUtterance(toWav(take, ctx.sampleRate), voiced, over, early);
      early = false;
    }
  };
  src.connect(proc);
  proc.connect(mute).connect(ctx.destination);
  return {
    async resume() {
      if (ctx.state !== "running") {
        // without a user gesture resume() may never settle: do not wait for it longer than a moment
        await Promise.race([ctx.resume().catch(() => undefined), new Promise((r) => setTimeout(r, 700))]);
      }
      return ctx.state === "running";
    },
    stop() {
      if (stopped) return;
      stopped = true;
      proc.disconnect();
      src.disconnect();
      stream.getTracks().forEach((t) => t.stop());
      void ctx.close();
      opts.onLevel?.(0);
    },
  };
}

/** What Whisper tends to "hear" in silence or noise - never treat these as a command. */
const GHOSTS = /^(thank you|thanks( for watching)?|you|bye|okay|ok|\.+|subtitles by.*|благодаря( ви)?( за вниманието)?|абонирайте се.*|субтитри.*|продължава.*)[.!?… ]*$/i;

export function isGhost(text: string, ms: number): boolean {
  const t = text.trim();
  return !t || (ms < 1500 && GHOSTS.test(t));
}

/** True when what was "heard" is mostly Vaelon's own sentence coming back through the speakers. */
export function isEcho(heard: string, spoken: string): boolean {
  const words = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}\s]/gu, " ").split(/\s+/).filter((w) => w.length > 1);
  const h = words(heard);
  if (h.length < 2 || !spoken) return false;
  const said = new Set(words(spoken));
  return h.filter((w) => said.has(w)).length / h.length >= 0.7;
}

const STOP_CORE = "stop|cancel|quiet|silence|enough|shut up|never ?mind|спри|стоп|стига|тихо|млъкни|отказ|откажи";
const STOP_RX = new RegExp(`^(please |ok(ay)?,? |vaelon,? |вейлон,? )?(${STOP_CORE})( it| that| now| talking| please| се| вече)*[.!?… ]*$`, "i");
// while Vaelon talks, the first sound of a short word is easily lost ("stop" arrives as "top")
const STOP_OVER_RX = /^(s?top|'?top it|спри|при|топ)[.!?… ]*$/i;

/** "Stop" in any of its forms. `over` = it was said while Vaelon was talking. */
export function isStop(text: string, over: boolean): boolean {
  const t = text.trim();
  return STOP_RX.test(t) || (over && STOP_OVER_RX.test(t));
}

/** A single short word said over Vaelon's voice ("yes", "ok", "mhm") is listening noise, not an interruption. */
export function isBackchannel(text: string): boolean {
  return text.trim().split(/\s+/).filter(Boolean).length <= 1;
}
