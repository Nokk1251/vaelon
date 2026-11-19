// Directs the swarm's menace: it tears and turns red at RANDOM moments, using one of several
// different effects each time (never the same one twice in a row, never on a fixed beat).

export type FxTarget = {
  setFx(threat: number, glitch: number, seed: number): void;
};

export type CssFx = { body: string; overlay: string };

type Step = { wait: number; threat?: number; glitch?: number; body?: string; overlay?: string };

const rnd = (a: number, b: number) => a + Math.random() * (b - a);
const pick = <T,>(xs: T[]) => xs[Math.floor(Math.random() * xs.length)];

/** Each effect is a short script of steps (wait ms, then apply values). */
const EFFECTS: Record<string, () => Step[]> = {
  // 1. instant blood-red flash with chromatic tear
  redFlash: () => [
    { wait: 0, threat: 1, glitch: 0.6, body: "fx-split", overlay: "bars-a" },
    { wait: rnd(120, 420), threat: 0.35, glitch: 0.2, body: "", overlay: "" },
    { wait: rnd(40, 90), threat: 0, glitch: 0 },
  ],
  // 2. orange stays; only the picture shreds into slices
  sliceTear: () => {
    const s: Step[] = [];
    for (let i = 0; i < Math.floor(rnd(3, 7)); i++) s.push({ wait: i ? rnd(30, 70) : 0, glitch: rnd(0.6, 1), body: "fx-shake", overlay: "bars-b" });
    s.push({ wait: rnd(40, 90), glitch: 0, body: "", overlay: "" });
    return s;
  },
  // 3. strobing stutter between orange and red
  stutter: () => {
    const s: Step[] = [];
    const n = Math.floor(rnd(3, 7));
    for (let i = 0; i < n; i++) {
      s.push({ wait: i ? rnd(25, 110) : 0, threat: i % 2 === 0 ? 1 : 0, glitch: i % 2 === 0 ? 0.4 : 0, body: i % 2 === 0 ? "fx-flicker" : "" });
    }
    s.push({ wait: rnd(30, 80), threat: 0, glitch: 0, body: "" });
    return s;
  },
  // 4. slow menacing burn: the core bleeds into red, holds, then fades back
  slowBurn: () => {
    const s: Step[] = [];
    for (let i = 1; i <= 8; i++) s.push({ wait: i === 1 ? 0 : rnd(60, 110), threat: i / 8 });
    s.push({ wait: rnd(600, 1800), glitch: 0.3, overlay: "bars-c" });
    s.push({ wait: rnd(60, 160), glitch: 0, overlay: "" });
    for (let i = 7; i >= 0; i--) s.push({ wait: rnd(70, 130), threat: i / 8 });
    return s;
  },
  // 5. violent shake with heavy colour split, quick red pulse
  seizure: () => [
    { wait: 0, threat: 0.7, glitch: 1, body: "fx-shake fx-split", overlay: "bars-a" },
    { wait: rnd(50, 90), threat: 0, glitch: 0.5, overlay: "bars-c" },
    { wait: rnd(50, 90), threat: 1, glitch: 1, overlay: "bars-b" },
    { wait: rnd(80, 160), threat: 0, glitch: 0, body: "", overlay: "" },
  ],
  // 6. dim flicker like failing power, with a brief red heartbeat
  heartbeat: () => [
    { wait: 0, threat: 0.55, body: "fx-flicker" },
    { wait: rnd(110, 160), threat: 0.1 },
    { wait: rnd(90, 140), threat: 0.8, glitch: 0.25 },
    { wait: rnd(160, 300), threat: 0, glitch: 0, body: "" },
  ],
};

export class GlitchDirector {
  private timers = new Set<ReturnType<typeof setTimeout>>();
  private running = false;
  private busy = false;
  private last = "";
  private seed = 0;
  /** Called whenever an effect starts, with its approximate duration in ms. */
  onFire?: (durationMs: number, effect: string) => void;

  constructor(private target: () => FxTarget | null, private css: (fx: CssFx) => void) {}

  setBusy(b: boolean) {
    this.busy = b;
  }

  start() {
    if (this.running) return;
    this.running = true;
    this.schedule();
  }

  stop() {
    this.running = false;
    this.timers.forEach(clearTimeout);
    this.timers.clear();
    this.target()?.setFx(0, 0, 0);
    this.css({ body: "", overlay: "" });
  }

  private after(ms: number, fn: () => void) {
    const t = setTimeout(() => {
      this.timers.delete(t);
      fn();
    }, ms);
    this.timers.add(t);
  }

  /** Irregular gaps: exponential-ish distribution so it never feels like a metronome. */
  private nextGap(): number {
    const mean = this.busy ? 1800 : 5200;
    return 700 + -Math.log(1 - Math.random() * 0.97) * mean;
  }

  private schedule() {
    if (!this.running) return;
    this.after(this.nextGap(), () => {
      this.play();
      this.schedule();
    });
  }

  private play() {
    const names = Object.keys(EFFECTS).filter((n) => n !== this.last);
    const name = pick(names);
    this.last = name;
    let threat = 0;
    let glitch = 0;
    let at = 0;
    for (const step of EFFECTS[name]()) {
      at += step.wait;
      this.after(at, () => {
        if (step.threat !== undefined) threat = step.threat;
        if (step.glitch !== undefined) glitch = step.glitch;
        this.seed = Math.random() * 100;
        this.target()?.setFx(threat, glitch, this.seed);
        if (step.body !== undefined || step.overlay !== undefined) {
          this.css({ body: step.body ?? "", overlay: step.overlay ?? "" });
        }
      });
    }
    this.onFire?.(at + 200, name);
    // safety net: always end clean
    this.after(at + 200, () => {
      this.target()?.setFx(0, 0, this.seed);
      this.css({ body: "", overlay: "" });
    });
  }
}
