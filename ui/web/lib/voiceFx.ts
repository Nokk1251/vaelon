// Voice glitch: when the orb glitches, Vaelon's voice tears with it - pitch warp, ring-modulated static,
// stutter cuts and a short digital burst. Pure WebAudio, runs locally in the browser.

let ctx: AudioContext | null = null;
let enabled = false;
let input: GainNode | null = null;
let dry: GainNode | null = null;
let wet: GainNode | null = null;
let master: GainNode | null = null;
let ringOsc: OscillatorNode | null = null;
let current: HTMLAudioElement | PcmPlayer | null = null;
let analyser: AnalyserNode | null = null;
let probe: Float32Array<ArrayBuffer> | null = null;

function build(): AudioContext | null {
  if (ctx) return ctx;
  if (typeof window === "undefined" || !("AudioContext" in window)) return null;
  const c = new AudioContext();
  input = c.createGain();
  dry = c.createGain();
  wet = c.createGain();
  master = c.createGain();
  wet.gain.value = 0;
  // ring modulator branch: signal multiplied by a low oscillator = metallic, broken sound
  const ring = c.createGain();
  ring.gain.value = 0;
  ringOsc = c.createOscillator();
  ringOsc.frequency.value = 90;
  ringOsc.connect(ring.gain);
  ringOsc.start();
  const shaper = c.createWaveShaper();
  const curve = new Float32Array(256);
  for (let i = 0; i < 256; i++) {
    const x = (i / 255) * 2 - 1;
    curve[i] = Math.tanh(x * 4); // hard-ish clipping
  }
  shaper.curve = curve;
  input.connect(dry).connect(master);
  input.connect(ring).connect(shaper).connect(wet).connect(master);
  master.connect(c.destination);
  analyser = c.createAnalyser();
  analyser.fftSize = 512;
  probe = new Float32Array(new ArrayBuffer(analyser.fftSize * 4));
  master.connect(analyser);
  ctx = c;
  return c;
}

let voiceGlitch = true; // Settings > Look and sound: the voice may crackle with the swarm's glitches

export function setVoiceGlitch(on: boolean) {
  voiceGlitch = on;
}

/** Call from a user gesture (the VOICE button) so the browser allows audio. */
export function setVoiceFx(on: boolean) {
  enabled = on;
  if (on) {
    const c = build();
    void c?.resume();
  }
}

/** Route a clip through the effect chain; returns false if WebAudio is unavailable (plain playback then). */
export function routeAudio(a: HTMLAudioElement): boolean {
  const c = build();
  if (!c || !input) return false;
  try {
    c.createMediaElementSource(a).connect(input);
    current = a;
    a.addEventListener("ended", () => {
      if (current === a) current = null;
    });
    return true;
  } catch {
    return false;
  }
}

/** Is Vaelon's neural voice playing right now? */
export function isSpeaking(): boolean {
  if (current instanceof PcmPlayer) return current.started && !current.paused && !current.ended;
  return !!current && !current.paused && !current.ended;
}

/** Plays raw 16-bit mono audio while it is still arriving (the streamed cloud voice), through the same effect chain
 *  as every other clip. It waits until `lead` seconds are buffered before the first sound, so a slow network
 *  stutters less; later pieces are placed seamlessly one after another. Pause = the voice's audio engine waits. */
export class PcmPlayer {
  started = false;
  paused = false;
  ended = false;
  onstart?: () => void;
  readonly done: Promise<void>;
  private resolve!: () => void;
  private at = 0;
  private live = 0;
  private closed = false;
  private waiting: Float32Array[] = [];
  private waitingLen = 0;
  private sources = new Set<AudioBufferSourceNode>();

  constructor(private rate: number, private lead = 0.15) {
    this.done = new Promise<void>((r) => (this.resolve = r));
    build();
    current = this;
  }

  /** Can it make sound at all? (Audio is locked until the first click in a window opened by a script.) */
  async ready(ms = 700): Promise<boolean> {
    const c = build();
    if (!c) return false;
    if (c.state !== "running" && !this.paused) {
      await Promise.race([c.resume().catch(() => undefined), new Promise((r) => setTimeout(r, ms))]);
    }
    return c.state === "running" || this.paused;
  }

  push(pcm: Int16Array) {
    if (this.ended || !pcm.length) return;
    const f = new Float32Array(pcm.length);
    for (let i = 0; i < pcm.length; i++) f[i] = pcm[i] / 32768;
    if (this.started) return this.schedule(f);
    this.waiting.push(f);
    this.waitingLen += f.length;
    if (this.waitingLen / this.rate >= this.lead) this.begin();
  }

  /** No more audio is coming. */
  finish() {
    this.closed = true;
    if (!this.started && this.waitingLen) this.begin();
    this.check();
  }

  pause() {
    this.paused = true;
    void ctx?.suspend();
  }

  play(): Promise<void> {
    this.paused = false;
    return ctx ? ctx.resume() : Promise.resolve();
  }

  stop() {
    for (const s of this.sources) {
      try {
        s.stop();
      } catch {
        /* not started yet */
      }
    }
    this.sources.clear();
    this.live = 0;
    this.waiting = [];
    this.waitingLen = 0;
    this.closed = true;
    if (this.paused) void this.play(); // the next clip must not find the voice engine still waiting
    this.check();
  }

  private begin() {
    const all = new Float32Array(this.waitingLen);
    let o = 0;
    for (const w of this.waiting) {
      all.set(w, o);
      o += w.length;
    }
    this.waiting = [];
    this.waitingLen = 0;
    this.started = true;
    this.schedule(all);
    this.onstart?.();
  }

  private schedule(f: Float32Array) {
    const c = ctx;
    if (!c || !input || !f.length) return;
    const b = c.createBuffer(1, f.length, this.rate);
    b.getChannelData(0).set(f);
    const s = c.createBufferSource();
    s.buffer = b;
    s.connect(input);
    const t = Math.max(this.at, c.currentTime + 0.02); // late piece: a short gap instead of a lost one
    s.start(t);
    this.at = t + b.duration;
    this.live++;
    this.sources.add(s);
    s.onended = () => {
      if (!this.sources.delete(s)) return;
      this.live--;
      this.check();
    };
  }

  private check() {
    if (this.closed && this.live <= 0 && !this.waitingLen && !this.ended) {
      this.ended = true;
      if (current === this) current = null;
      this.resolve();
    }
  }
}

/** Loudness of Vaelon's voice right now, 0..1 (drives the swarm while it speaks). */
export function voiceLevel(): number {
  if (!analyser || !probe || !isSpeaking()) return 0;
  analyser.getFloatTimeDomainData(probe);
  let sum = 0;
  for (let i = 0; i < probe.length; i++) sum += probe[i] * probe[i];
  return Math.min(1, Math.sqrt(sum / probe.length) * 4.5);
}

function burst(c: AudioContext, ms: number) {
  const len = Math.max(1, Math.floor((c.sampleRate * ms) / 1000));
  const buf = c.createBuffer(1, len, c.sampleRate);
  const d = buf.getChannelData(0);
  for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * (1 - i / len);
  const src = c.createBufferSource();
  src.buffer = buf;
  const band = c.createBiquadFilter();
  band.type = "bandpass";
  band.frequency.value = 400 + Math.random() * 3000;
  band.Q.value = 2 + Math.random() * 6;
  const g = c.createGain();
  g.gain.value = 0.05;
  src.connect(band).connect(g).connect(master ?? c.destination);
  src.start();
}

/** Fire a voice glitch lasting about `ms`, in sync with a visual glitch. */
export function triggerVoiceGlitch(ms: number) {
  const c = ctx;
  if (!enabled || !voiceGlitch || !c || !wet || !dry || !master || !ringOsc) return;
  // only while Vaelon is actually speaking - silence stays silent
  const a = current;
  if (!a || a.paused || a.ended || (a instanceof PcmPlayer && !a.started)) return;
  const t = c.currentTime;
  const dur = Math.min(Math.max(ms, 90), 600) / 1000; // short and light
  const kind = Math.floor(Math.random() * 4);

  // a faint digital crackle inside the voice (routed through the voice chain, not on its own)
  burst(c, 40 + Math.random() * 80);

  // ring-modulated, clipped "broken speaker" blend with a sweeping carrier
  wet.gain.cancelScheduledValues(t);
  dry.gain.cancelScheduledValues(t);
  ringOsc.frequency.cancelScheduledValues(t);
  wet.gain.setValueAtTime(0.35, t);
  dry.gain.setValueAtTime(0.75, t);
  ringOsc.frequency.setValueAtTime(40 + Math.random() * 120, t);
  ringOsc.frequency.linearRampToValueAtTime(80 + Math.random() * 500, t + dur);
  wet.gain.setValueAtTime(0, t + dur);
  dry.gain.setValueAtTime(1, t + dur);

  // stutter: rapid cuts of the master volume
  if (kind === 0 || kind === 3) {
    master.gain.cancelScheduledValues(t);
    let at = 0;
    while (at < dur) {
      const cut = 0.012 + Math.random() * 0.025;
      master.gain.setValueAtTime(0, t + at);
      master.gain.setValueAtTime(1, t + at + cut);
      at += cut + 0.03 + Math.random() * 0.08;
    }
    master.gain.setValueAtTime(1, t + dur + 0.01);
  }

  // pitch warp: the voice drops or jumps, then recovers
  if ((kind === 1 || kind === 3) && a instanceof HTMLAudioElement) {
    const rate = a.playbackRate;
    a.preservesPitch = false;
    a.playbackRate = Math.random() < 0.5 ? 0.82 + Math.random() * 0.08 : 1.1 + Math.random() * 0.1;
    setTimeout(() => {
      a.playbackRate = rate;
      a.preservesPitch = true;
    }, Math.min(dur * 1000, 700));
  }
}
