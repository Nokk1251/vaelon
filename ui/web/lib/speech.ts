// Speaks Vaelon's answers sentence by sentence while they stream in.
// Privacy: ONLY voices flagged localService are used, so text is never sent to a cloud TTS.

import { API_BASE } from "./vaelonApi";
import { PcmPlayer, isSpeaking, routeAudio } from "./voiceFx";

/** Audio of one sentence that is still arriving from the core (the streamed cloud voice). Read at once, played
 *  when its turn comes - so the core never waits for the app, and nothing is lost while an earlier sentence plays. */
class PcmFeed {
  chunks: Int16Array[] = [];
  done = false;
  private wake: (() => void)[] = [];

  constructor(readonly rate: number) {}

  push(c: Int16Array) {
    this.chunks.push(c);
    this.ping();
  }

  end() {
    this.done = true;
    this.ping();
  }

  /** Resolves when there is more than `have` pieces, or when the audio is complete. */
  more(have: number): Promise<void> {
    if (this.chunks.length > have || this.done) return Promise.resolve();
    return new Promise((r) => this.wake.push(r));
  }

  private ping() {
    const w = this.wake;
    this.wake = [];
    w.forEach((r) => r());
  }
}

async function readPcm(res: Response, feed: PcmFeed) {
  const reader = res.body?.getReader();
  let carry: Uint8Array | null = null;
  try {
    for (;;) {
      if (!reader) break;
      const { done, value } = await reader.read();
      if (done || !value) break;
      let bytes: Uint8Array = value;
      if (carry) {
        const joined = new Uint8Array(carry.length + bytes.length);
        joined.set(carry);
        joined.set(bytes, carry.length);
        bytes = joined;
        carry = null;
      }
      const even = bytes.length - (bytes.length % 2); // a sample can be split between two network pieces
      if (even < bytes.length) carry = bytes.slice(even);
      if (even) feed.push(new Int16Array(bytes.slice(0, even).buffer));
    }
  } catch {
    /* cancelled, or the connection dropped: play what arrived */
  }
  feed.end();
}

type Clip = { blob: Blob } | { feed: PcmFeed };

const SENTENCE_END = /[.!?…]+["')\]]?\s/g;

function pickLocalVoice(text: string): SpeechSynthesisVoice | null {
  const lang = /[Ѐ-ӿ]/.test(text) ? "bg" : "en";
  const local = window.speechSynthesis.getVoices().filter((v) => v.localService);
  return local.find((v) => v.lang.toLowerCase().startsWith(lang)) ?? null;
}

/** What a listener should hear: no code blocks, tables, Markdown marks or LaTeX. */
export function speakable(md: string): string {
  return md
    .replace(/```[\s\S]*?(```|$)/g, " ")
    .replace(/^\s*\|.*\|\s*$/gm, " ")
    .replace(/`([^`]*)`/g, "$1")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/\*\*|__|\*|~~/g, "")
    .replace(/^\s*[-+]\s+/gm, "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/\\[[\]()]/g, "")
    .replace(/-{3,}/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export class Speaker {
  private spoken = 0;
  private text = ""; // the answer as it was last fed
  /** Long answers (lessons, tables) are read only up to this many characters - the rest stays on screen.
   *  Saves time and cloud voice credits (ElevenLabs bills per character). */
  maxChars = 600;
  private voiced = 0;
  private cutNoted = false;
  /** Set to the API token to use Vaelon's own local neural voice (Piper); null = browser voices. */
  serverToken: string | null = null;
  private gen = 0;
  private queue: Promise<void> = Promise.resolve();
  private audio: HTMLAudioElement | PcmPlayer | null = null;
  private aborts = new Set<AbortController>(); // requests of the current answer: dropped on cancel()
  onNoVoice?: () => void;
  /** Called every time a clip really starts to sound (used by the /speed read-out). */
  onSound?: () => void;
  private warned = false;

  get supported(): boolean {
    return typeof window !== "undefined" && ("speechSynthesis" in window || this.serverToken !== null);
  }

  cancel() {
    this.gen++;
    this.queue = Promise.resolve();
    this.aborts.forEach((a) => a.abort()); // the core stops reading the cloud voice too
    this.aborts.clear();
    if (this.audio instanceof PcmPlayer) this.audio.stop();
    else {
      this.audio?.dispatchEvent(new Event("ended")); // release anything waiting on this clip
      this.audio?.pause();
    }
    this.audio = null;
    if (this.supported) window.speechSynthesis.cancel();
    this.spoken = 0;
    this.text = "";
    this.voiced = 0;
    this.cutNoted = false;
    this.held = false;
    this.recent = "";
  }

  private say(chunk: string) {
    let text = speakable(chunk);
    if (!text) return;
    this.recent = (this.recent + " " + text).slice(-1200);
    if (this.voiced >= this.maxChars) {
      if (this.cutNoted) return;
      this.cutNoted = true;
      text = /[Ѐ-ӿ]/.test(text) ? "Останалото е на екрана." : "The rest is on screen.";
    } else {
      this.voiced += text.length;
    }
    if (!this.serverToken) return this.localSay(text);
    const g = this.gen;
    const token = this.serverToken;
    const abort = new AbortController();
    this.aborts.add(abort);
    // Start synthesising right away (pipelined); play clips strictly in order. `stream`: if the voice comes from the
    // cloud the core sends it while it arrives (raw PCM); a local or already-spoken sentence comes as a whole clip.
    const clip: Promise<Clip> = fetch(`${API_BASE}/tts`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ text, stream: true }),
      signal: abort.signal,
    }).then(async (r) => {
      if (!r.ok) throw new Error(String(r.status));
      if (!(r.headers.get("Content-Type") ?? "").startsWith("audio/L16")) return { blob: await r.blob() };
      const feed = new PcmFeed(Number(r.headers.get("X-Sample-Rate")) || 22050);
      void readPcm(r, feed).finally(() => this.aborts.delete(abort));
      return { feed };
    });
    this.queue = this.queue.then(async () => {
      if (g !== this.gen) return;
      let got: Clip;
      try {
        got = await clip;
      } catch {
        if (g === this.gen) this.localSay(text);
        return;
      }
      if (g !== this.gen) return;
      if ("feed" in got) return this.playFeed(got.feed, g);
      this.aborts.delete(abort);
      const blob = got.blob;
      const url = URL.createObjectURL(blob);
      const a = new Audio(url);
      routeAudio(a); // glitch-capable path (falls back to plain playback)
      this.audio = a;
      await new Promise<void>((resolve) => {
        a.onended = a.onerror = () => resolve();
        if (this.held) return; // you are talking: hold(false) starts it, cancel() drops it
        a.play().then(() => this.onSound?.()).catch(() => resolve());
      });
      URL.revokeObjectURL(url);
    });
  }

  /** Play a sentence that is still arriving: the first sound comes after ~0.15 s of audio, not after all of it. */
  private async playFeed(feed: PcmFeed, g: number) {
    const p = new PcmPlayer(feed.rate);
    this.audio = p;
    if (this.held) p.pause(); // you are talking: hold(false) lets it play, cancel() drops it
    if (!(await p.ready())) {
      p.stop();
      return; // audio is locked in this window (no click yet): skip, like a clip that cannot play
    }
    p.onstart = () => this.onSound?.();
    let have = 0;
    for (;;) {
      await feed.more(have);
      if (g !== this.gen) return p.stop();
      while (have < feed.chunks.length) p.push(feed.chunks[have++]);
      if (feed.done && have >= feed.chunks.length) break;
    }
    p.finish();
    await p.done;
  }

  /** Chrome fills the voice list asynchronously: wait for it instead of failing silently. */
  private async voicesReady(): Promise<void> {
    const synth = window.speechSynthesis;
    if (synth.getVoices().length) return;
    await new Promise<void>((resolve) => {
      const done = () => {
        synth.removeEventListener("voiceschanged", done);
        resolve();
      };
      synth.addEventListener("voiceschanged", done);
      setTimeout(done, 1500);
    });
  }

  private held = false;

  /** Pause (true) or resume (false) the voice without losing its place - used when you start talking over it:
   *  if it was a real interruption the caller cancels, if it was only noise the sentence simply goes on. */
  hold(on: boolean) {
    if (on === this.held) return;
    this.held = on;
    const synth = typeof window !== "undefined" && "speechSynthesis" in window ? window.speechSynthesis : null;
    if (on) {
      this.audio?.pause();
      synth?.pause();
    } else {
      void this.audio?.play().catch(() => undefined);
      synth?.resume();
    }
  }

  /** Everything said (or queued) for the current answer, as text - to recognise Vaelon's own echo in the microphone. */
  recent = "";

  /** Speak a finished answer after whatever is already being said (a second task that ended meanwhile). */
  announce(full: string) {
    if (!this.supported) return;
    const keep: [number, boolean] = [this.voiced, this.cutNoted];
    this.voiced = 0;
    this.cutNoted = false;
    const parts = full.match(/[^.!?…]+[.!?…]*["')\]]?\s*/g) ?? [full];
    for (const part of parts) this.say(part);
    [this.voiced, this.cutNoted] = keep;
  }

  /** True while any voice (neural or browser) is talking. */
  get speaking(): boolean {
    return isSpeaking() || (typeof window !== "undefined" && "speechSynthesis" in window && window.speechSynthesis.speaking);
  }

  /** Play a ready clip through the voice chain (used by the Voice Designer preview). */
  playBlob(blob: Blob) {
    this.cancel();
    const url = URL.createObjectURL(blob);
    const a = new Audio(url);
    routeAudio(a);
    this.audio = a;
    a.onended = () => URL.revokeObjectURL(url);
    void a.play().catch(() => undefined);
  }

  get mode(): "neural" | "browser" {
    return this.serverToken ? "neural" : "browser";
  }

  private localSay(chunk: string) {
    void this.localSayAsync(chunk);
  }

  private async localSayAsync(chunk: string) {
    const text = chunk.trim();
    if (!text || !("speechSynthesis" in window)) return;
    await this.voicesReady();
    const voice = pickLocalVoice(text);
    if (!voice) {
      if (!this.warned) {
        this.warned = true;
        this.onNoVoice?.();
      }
      return;
    }
    const u = new SpeechSynthesisUtterance(text);
    u.voice = voice;
    u.lang = voice.lang;
    u.rate = 1.0;
    u.pitch = 0.8; // slightly deeper, Vaelon-ish
    u.onstart = () => this.onSound?.();
    window.speechSynthesis.speak(u);
  }

  /** Call with the full text received so far; speaks any newly completed sentences. */
  feed(full: string) {
    if (!this.supported) return;
    if (this.spoken) {
      // the same answer can come back trimmed (the finished answer has no trailing space, the streamed one had):
      // that is NOT a new text - starting over would repeat everything already said
      const said = this.text.slice(0, this.spoken).trim();
      const at = said ? full.indexOf(said) : -1;
      if (at >= 0 && at <= 2) this.spoken = at + said.length;
      else this.cancel(); // the text really was replaced (e.g. translated): say the new one from the start
    }
    this.text = full;
    let end = this.spoken;
    SENTENCE_END.lastIndex = this.spoken;
    for (let m = SENTENCE_END.exec(full); m; m = SENTENCE_END.exec(full)) end = m.index + m[0].length;
    if (end === this.spoken && this.spoken === 0 && full.length > 70) {
      // first words of a long opening sentence: start talking at the first comma instead of waiting for the full stop
      const m = /^[\s\S]{35,}?[,;:]\s/.exec(full);
      if (m) end = m[0].length;
    }
    if (end > this.spoken) {
      this.say(full.slice(this.spoken, end));
      this.spoken = end;
    }
  }

  /** Call once with the final text; speaks whatever is left. */
  finish(full: string) {
    if (!this.supported) return;
    this.feed(full);
    this.say(full.slice(this.spoken));
    this.spoken = 0;
    this.text = "";
  }
}
