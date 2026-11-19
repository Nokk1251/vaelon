// Small helpers that make a spoken exchange start sooner, and a stopwatch that shows where its time went.

import type { VaelonApi } from "./vaelonApi";

const SPEED_KEY = "vaelon_speed";

export function speedOn(): boolean {
  try {
    return localStorage.getItem(SPEED_KEY) === "1";
  } catch {
    return false;
  }
}

export function setSpeed(on: boolean) {
  try {
    if (on) localStorage.setItem(SPEED_KEY, "1");
    else localStorage.removeItem(SPEED_KEY);
  } catch {
    /* private mode: the read-out simply stays off */
  }
}

/** Seconds from the moment you stopped talking (or pressed Enter) to: your words as text, the first words of the
 *  answer, the first sound of the voice. */
export class Stopwatch {
  private t0 = 0;
  private marks: Partial<Record<"heard" | "words" | "voice", number>> = {};
  private shown = true;

  /** `agoMs`: how long ago the moment really was (the microphone waits a little to be sure you have finished). */
  start(agoMs = 0) {
    this.t0 = performance.now() - agoMs;
    this.marks = {};
    this.shown = false;
  }

  mark(what: "heard" | "words" | "voice") {
    if (!this.shown && this.marks[what] === undefined) this.marks[what] = (performance.now() - this.t0) / 1000;
  }

  /** The read-out, once per exchange: when the answer is complete, or - if it is being spoken - when the voice starts.
   *  Returns "" while there is nothing (new) to show. */
  report(done: boolean, spoken: boolean, words: { heard: string; first: string; voice: string }): string {
    if (this.shown || this.marks.words === undefined) return "";
    if (spoken && this.marks.voice === undefined && !done) return "";
    if (spoken && this.marks.voice === undefined && done && performance.now() - this.t0 < 60000 && !this.waited) {
      this.waited = true; // the answer is complete but the voice has not started yet: one more chance
      return "";
    }
    this.shown = true;
    this.waited = false;
    const s = (n?: number) => (n === undefined ? "" : `${n.toFixed(2)} s`);
    return [
      this.marks.heard !== undefined ? `${words.heard} ${s(this.marks.heard)}` : "",
      `${words.first} ${s(this.marks.words)}`,
      this.marks.voice !== undefined ? `${words.voice} ${s(this.marks.voice)}` : "",
    ]
      .filter(Boolean)
      .join(" · ");
  }

  private waited = false;
}

/** Start turning speech into text while the microphone is still making sure that you have finished.
 *  `early(wav)` is called at a short pause; if you then stay silent, `final` hands back that transcript instead of
 *  starting a new one - a few tenths of a second saved on every phrase. If you go on talking, the early
 *  transcript is simply dropped. The same audio goes to the same engine as before, only a moment sooner. */
export class EarlyText {
  private pending: Promise<string> | null = null;

  constructor(private transcribe: (wav: Blob) => Promise<string>) {}

  early(wav: Blob) {
    const p = this.transcribe(wav).catch(() => "");
    this.pending = p;
  }

  async final(wav: Blob, early: boolean): Promise<string> {
    const p = early ? this.pending : null;
    this.pending = null;
    const text = p ? (await p).trim() : "";
    return text || (await this.transcribe(wav)).trim();
  }

  drop() {
    this.pending = null;
  }
}

let lastWarm = 0;

/** You started talking or typing: have the core open the connections your next request needs (at most every 15 s).
 *  Nothing is sent to anyone - see `vaelon/speed.py`. */
export function warmUp(api: VaelonApi) {
  const now = Date.now();
  if (now - lastWarm < 15000) return;
  lastWarm = now;
  void api.warm().catch(() => undefined);
}
