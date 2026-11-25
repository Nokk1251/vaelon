// The Swarm: Vaelon's body. Thousands of particles fly like a murmuration - no face, no fixed shape.
// Each particle chases a point on one of several invisible ribbons whose control points drift through
// space; the ribbons fold, twist, split and merge, and a turbulence field breaks every outline.
// It never plays the same way twice: every start draws a fresh random seed (crypto) that moves every path,
// picks one of several entrances and a tint, and while idle the flock now and then gathers into a figure -
// a sphere, a torus, a double helix, a galaxy, a wave, the dotted V - at random moments, sizes and angles.

import * as THREE from "three";

export type SwarmApi = {
  /** threat 0..1 (ember orange -> blood red), glitch 0..1 (tearing + scatter), seed changes the tear pattern */
  setFx(threat: number, glitch: number, seed: number): void;
  /** 0 calm .. 1 agitated (Vaelon is working) */
  setEnergy(e: number): void;
  /** idle: slow breathing murmuration | think: a spinning vortex with neural sparks |
   *  tool: tight orbiting rings | speak: a pulsing core that follows the voice */
  setMode(m: SwarmMode): void;
  /** voice loudness 0..1 while Vaelon speaks */
  setVoice(level: number): void;
  /** a shockwave through the swarm (a tool fired, a fact was learned) */
  pulse(strength?: number): void;
  /** Two or more running tasks: the swarm splits into one cluster per task (own colour, own shape).
   *  Fewer than two: the clusters flow back into one body. */
  setTasks(tasks: SwarmTask[]): void;
  /** Where a task's cluster is on screen (px inside the stage) - for its label. null when not split. */
  taskScreen(slot: number): { x: number; y: number; r: number } | null;
  /** a task finished: its cluster bursts before the matter rejoins the rest */
  burst(slot: number): void;
  /** microphone loudness 0..1 while Vaelon listens */
  setMic(level: number): void;
  /** gather into a figure now (sphere, torus, helix, galaxy, wave, vmark; none = a random one) */
  figure(kind?: string): void;
  /** what this start looks like: entrance, tint, seed, the figure being formed (for tests and curiosity) */
  readonly look: { entrance: string; tint: number[]; seed: number; figure: string | null };
  /** is the swarm being drawn, and if not, why (no WebGL, context lost) - also shown as the stage's fallback glow */
  status(): { drawing: boolean; reason: string };
  dispose(): void;
};

const TAU = Math.PI * 2;
export type SwarmMode = "idle" | "think" | "tool" | "speak" | "listen";
/** wait = queued, think = the model is working, tool = a tool is running */
export type SwarmTask = { id: string; slot: number; mode: "wait" | "think" | "tool" };
/** One colour per task slot: the cluster, its label and its chat bubble share it. */
export const TASK_COLORS = ["#ffb347", "#4fd8ff", "#c58bff", "#7dffa0"];
const TASK_RGB: [number, number, number][] = [[1.0, 0.7, 0.28], [0.31, 0.85, 1.0], [0.77, 0.55, 1.0], [0.49, 1.0, 0.63]];
// where the clusters sit (world units, x is scaled down on narrow windows) for 2, 3 and 4 tasks
const LAYOUT: Record<number, [number, number][]> = {
  2: [[-10.5, 6.4], [10.5, 6.4]],
  3: [[-14, 5.6], [0, 7.4], [14, 5.6]],
  4: [[-16.5, 5.2], [-5.6, 7.4], [5.6, 7.4], [16.5, 5.2]],
};
const CLUSTER_SCALE: Record<number, number> = { 2: 0.46, 3: 0.4, 4: 0.34 };

/** A random source for this start only: seeded from the operating system's crypto generator. */
function sessionRandom(): () => number {
  const a = new Uint32Array(2);
  try {
    crypto.getRandomValues(a);
  } catch {
    a[0] = (Date.now() ^ (performance.now() * 1000)) >>> 0;
  }
  let s = (a[0] ^ (a[1] << 7)) >>> 0 || 0x9e3779b9;
  return () => {
    // xorshift32
    s ^= s << 13;
    s >>>= 0;
    s ^= s >>> 17;
    s ^= s << 5;
    s >>>= 0;
    return s / 4294967296;
  };
}

type FormKind = "sphere" | "torus" | "helix" | "galaxy" | "wave" | "vmark";
export const FORMS: FormKind[] = ["sphere", "torus", "helix", "galaxy", "wave", "vmark"];
type Entrance = "scatter" | "bang" | "rain" | "ring" | "stream" | "spiral";
const ENTRANCES: Entrance[] = ["scatter", "bang", "rain", "ring", "stream", "spiral"];
/** Gentle per-start tints inside the ember palette (the brand stays orange-red). */
const TINTS: [number, number, number][] = [[1, 1, 1], [1.06, 0.94, 0.82], [1.0, 0.9, 0.7], [1.05, 0.84, 0.8], [0.98, 0.98, 0.92]];

/** Where particle i sits in figure `kind` (before rotation and scaling). sd, uu, ox/oy/oz: its fixed randoms. */
export function formPoint(kind: FormKind, i: number, sd: number, uu: number, ox: number, oy: number, oz: number, t: number,
  p: number, out: THREE.Vector3) {
  switch (kind) {
    case "sphere": {
      const len = Math.hypot(ox, oy, oz) || 1;
      const r = 6 * (0.86 + 0.14 * sd) * (1 + 0.04 * Math.sin(t * 2.2 + sd * 20));
      return out.set((ox / len) * r, (oy / len) * r, (oz / len) * r);
    }
    case "torus": {
      const a = uu * TAU + t * 0.5 * p, b = sd * TAU + t * 0.9;
      const R = 6, r = 1.6 + 0.6 * Math.sin(a * 3 + t);
      return out.set((R + r * Math.cos(b)) * Math.cos(a), (R + r * Math.cos(b)) * Math.sin(a), r * Math.sin(b)); // faces the camera
    }
    case "helix": {
      const strand = i % 2;
      const ang = uu * TAU * 2.4 + t * 1.2 * p + strand * Math.PI;
      const rung = i % 11 === 0; // a few particles form the rungs between the strands
      const R = rung ? 3.2 * (sd * 2 - 1) : 3.2;
      return out.set(Math.cos(ang) * R, (uu - 0.5) * 18, Math.sin(ang) * R);
    }
    case "galaxy": {
      const arm = i % 3;
      const r = 1 + Math.pow(sd, 0.75) * 9;
      const ang = r * 0.42 + (arm * TAU) / 3 + t * 0.35 * p + (uu - 0.5) * 0.5;
      return out.set(Math.cos(ang) * r, Math.sin(ang) * r, oy * 0.9 * (1.4 - r / 10)); // faces the camera
    }
    case "wave": {
      const x = (uu - 0.5) * 24, z = (sd - 0.5) * 12;
      return out.set(x, Math.sin(x * 0.45 + t * 2.1 * p) * Math.cos(z * 0.5 + t * 1.3) * 2.4, z);
    }
    case "vmark": {
      // the dotted V of the logo: two arms meeting at the bottom, dots growing denser and bigger downwards
      const arm = i % 2 ? 1 : -1;
      const q = Math.pow(uu, 0.8); // 0 = tip of an arm, 1 = the bottom point
      const spread = 0.25 + q * 0.9;
      return out.set(arm * (1 - q) * 7.5 + (sd - 0.5) * spread, 6 - q * 12 + (oz - 0) * spread * 0.6, (ox - 0) * spread * 0.8);
    }
  }
}

function hash(n: number) {
  const s = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return s - Math.floor(s);
}

/** Smooth wandering path built from incommensurate sines (never repeats visibly). */
function wander(seed: number, t: number, out: THREE.Vector3, scale: number) {
  const a = 0.05 + hash(seed) * 0.06;
  const b = 0.04 + hash(seed + 1) * 0.07;
  const c = 0.03 + hash(seed + 2) * 0.05;
  out.set(
    Math.sin(t * a + seed) * scale + Math.sin(t * b * 2.3 + seed * 3) * scale * 0.45,
    Math.sin(t * b + seed * 2) * scale * 0.55 + Math.cos(t * c * 1.7) * scale * 0.3,
    Math.cos(t * c + seed * 5) * scale * 0.8 + Math.sin(t * a * 1.9 + seed) * scale * 0.3,
  );
  return out;
}

function catmull(p0: THREE.Vector3, p1: THREE.Vector3, p2: THREE.Vector3, p3: THREE.Vector3, u: number, out: THREE.Vector3) {
  const u2 = u * u;
  const u3 = u2 * u;
  out.set(0, 0, 0)
    .addScaledVector(p0, -0.5 * u3 + u2 - 0.5 * u)
    .addScaledVector(p1, 1.5 * u3 - 2.5 * u2 + 1)
    .addScaledVector(p2, -1.5 * u3 + 2 * u2 + 0.5 * u)
    .addScaledVector(p3, 0.5 * u3 - 0.5 * u2);
  return out;
}

/** 0..1, and 0 for anything that is not a number (a NaN would otherwise stay in the smoothing forever). */
const c01 = (v: number) => (Number.isFinite(v) ? Math.max(0, Math.min(1, v)) : 0);

export function createSwarm(container: HTMLElement, opts: { compact?: boolean } = {}): SwarmApi {
  const rnd = sessionRandom();
  const S = rnd() * 997; // this start's seed: shifts every random number below
  const tShift = rnd() * 900; // the wandering paths begin at a different point of their (never repeating) course
  // the companion's small orb: the far-away entrances (ring, rain, stream, spiral) start outside its little view and
  // left it EMPTY for seconds, and the big figures did not fit - so it always bursts from the centre, a bit further away
  const compact = !!opts.compact;
  const pick = Math.floor(rnd() * ENTRANCES.length);
  const entrance = compact ? "bang" : ENTRANCES[pick];
  const tint = TINTS[Math.floor(rnd() * TINTS.length)];
  const lowEnd = (navigator.hardwareConcurrency ?? 4) <= 4;
  const N = lowEnd ? 5000 : 9000;
  const CTRL = 5; // control points per ribbon
  const MAX_GROUPS = 4;

  // the size it draws at: never 0 (a minimised window shrinks the page to 0 x 0 and 0/0 made every particle NaN for good)
  let vw = Math.max(1, container.clientWidth), vh = Math.max(1, container.clientHeight);
  const pixelRatio = Math.min(window.devicePixelRatio || 1, 1.75);
  // the GPU drawing surface. Creating it can FAIL (no WebGL right now, e.g. after a GPU reset) and the browser can take
  // it away later (context lost). Either way the swarm waits and tries again instead of throwing - a throw here used
  // to unmount the whole app and leave the window blank.
  let renderer: THREE.WebGLRenderer | null = null;
  let lostAt = 0;
  let retryAt = 0;
  // While nothing can be drawn the stage shows a calm glow instead of an empty window (class swarm-fallback), and the
  // reason is logged once - so a missing swarm is visible and explainable, never just "gone".
  let fallbackReason = "";
  let drawing = false;
  const setFallback = (reason: string) => {
    drawing = !reason;
    container.classList.toggle("swarm-fallback", !!reason);
    if (reason && reason !== fallbackReason) {
      console.warn(`Vaelon swarm: ${reason} - showing the still glow and trying again every 3 seconds.`);
    } else if (!reason && fallbackReason) {
      console.info("Vaelon swarm: drawing again.");
    }
    fallbackReason = reason;
  };
  const makeRenderer = (): THREE.WebGLRenderer | null => {
    try {
      const r = new THREE.WebGLRenderer({ antialias: false, alpha: true, powerPreference: "high-performance" });
      r.setPixelRatio(pixelRatio);
      r.setSize(vw, vh);
      r.domElement.addEventListener("webglcontextlost", () => (lostAt = performance.now() || 1));
      r.domElement.addEventListener("webglcontextrestored", () => (lostAt = 0));
      container.appendChild(r.domElement);
      return r;
    } catch (e) {
      setFallback(`no WebGL (${e instanceof Error ? e.message.slice(0, 80) : "unknown"})`);
      return null;
    }
  };
  const dropRenderer = () => {
    if (!renderer) return;
    try {
      renderer.dispose();
      if (!lostAt) renderer.forceContextLoss(); // free the GPU context now, not whenever the garbage collector runs
    } catch {
      /* already gone */
    }
    renderer.domElement.remove();
    renderer = null;
  };
  renderer = makeRenderer();

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(55, vw / vh, 0.1, 200);
  camera.position.set(0, 0, compact ? 30 : 26);

  // --- particle state ---
  const pos = new Float32Array(N * 3);
  const vel = new Float32Array(N * 3);
  const u = new Float32Array(N); // position along its ribbon
  const off = new Float32Array(N * 3); // fixed offset from the ribbon centre line
  const grp = new Uint8Array(N);
  const seedAttr = new Float32Array(N);
  const slotOf = new Int8Array(N).fill(-1); // which task's cluster a particle belongs to (-1 = the one body)
  const taskAttrArr = new Float32Array(N).fill(-1);
  const side = rnd() < 0.5 ? -1 : 1;
  const spin0 = rnd() * TAU;
  for (let i = 0; i < N; i++) {
    u[i] = hash(i * 1.37 + S);
    const th = hash(i * 2.11 + S) * TAU;
    const ph = Math.acos(2 * hash(i * 3.7 + S) - 1);
    const r = Math.pow(hash(i * 5.3 + S), 0.6);
    off[i * 3] = Math.sin(ph) * Math.cos(th) * r;
    off[i * 3 + 1] = Math.sin(ph) * Math.sin(th) * r * 0.35; // flattened: sheets, not tubes
    off[i * 3 + 2] = Math.cos(ph) * r;
    seedAttr[i] = hash(i * 9.1 + S);
    // where it is when the window opens: one of several entrances, chosen at random each start
    const a = hash(i + S), b = hash(i + 7 + S), c = hash(i + 13 + S), i3 = i * 3;
    if (entrance === "bang") {
      pos[i3] = (a - 0.5) * 0.6; pos[i3 + 1] = (b - 0.5) * 0.6; pos[i3 + 2] = (c - 0.5) * 0.6;
      // erupts from the centre; the companion's orb shows only ~13 units, so its burst is smaller (it flew out of view)
      const d = compact ? 5 + hash(i * 1.9 + S) * 6 : 14 + hash(i * 1.9 + S) * 22;
      vel[i3] = Math.sin(ph) * Math.cos(th) * d; vel[i3 + 1] = Math.sin(ph) * Math.sin(th) * d; vel[i3 + 2] = Math.cos(ph) * d;
    } else if (entrance === "rain") {
      pos[i3] = (a - 0.5) * 44; pos[i3 + 1] = 16 + b * 26; pos[i3 + 2] = (c - 0.5) * 16;
      vel[i3 + 1] = -4 - b * 6;
    } else if (entrance === "ring") {
      const ang = a * TAU, R = 24 + (b - 0.5) * 3;
      pos[i3] = Math.cos(ang) * R; pos[i3 + 1] = Math.sin(ang) * R * 0.62; pos[i3 + 2] = (c - 0.5) * 4;
    } else if (entrance === "stream") {
      pos[i3] = side * (26 + a * 22); pos[i3 + 1] = (b - 0.5) * 10 + Math.sin(a * 9) * 4; pos[i3 + 2] = (c - 0.5) * 10;
      vel[i3] = -side * (6 + a * 8);
    } else if (entrance === "spiral") {
      const rr = 8 + a * 26, ang = rr * 0.35 + spin0 + (i % 2) * Math.PI;
      pos[i3] = Math.cos(ang) * rr; pos[i3 + 1] = (b - 0.5) * 3; pos[i3 + 2] = Math.sin(ang) * rr - 6;
    } else {
      pos[i3] = (a - 0.5) * 40; pos[i3 + 1] = (b - 0.5) * 24; pos[i3 + 2] = (c - 0.5) * 20;
    }
  }

  const geo = new THREE.BufferGeometry();
  const posAttr = new THREE.BufferAttribute(pos, 3);
  posAttr.setUsage(THREE.DynamicDrawUsage);
  geo.setAttribute("position", posAttr);
  geo.setAttribute("aSeed", new THREE.BufferAttribute(seedAttr, 1));
  const taskAttr = new THREE.BufferAttribute(taskAttrArr, 1);
  taskAttr.setUsage(THREE.DynamicDrawUsage);
  geo.setAttribute("aTask", taskAttr);

  const mat = new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    uniforms: {
      uTime: { value: 0 },
      uThreat: { value: 0 },
      uGlitch: { value: 0 },
      uSeed: { value: 0 },
      uPixel: { value: pixelRatio },
      uThink: { value: 0 },
      uVoice: { value: 0 },
      uBreath: { value: 0 },
      uSplit: { value: 0 },
      uTaskCol: { value: TASK_RGB.map((c) => new THREE.Vector3(c[0], c[1], c[2])) },
      uTint: { value: new THREE.Vector3(tint[0], tint[1], tint[2]) },
      uPhase: { value: rnd() * 100 },
      uShimmer: { value: 0.12 + rnd() * 0.3 },
      uShimmerDir: { value: new THREE.Vector2(Math.cos(rnd() * TAU), Math.sin(rnd() * TAU)) },
    },
    vertexShader: /* glsl */ `
      attribute float aSeed;
      attribute float aTask;
      uniform float uTime, uGlitch, uSeed, uPixel, uThink, uVoice, uBreath, uPhase, uShimmer;
      uniform vec2 uShimmerDir;
      varying float vSeed;
      varying float vShine;
      varying float vTask;
      varying float vDepth;
      varying float vSpark;
      float h(float n) { return fract(sin(n) * 43758.5453); }
      void main() {
        vec3 p = position;
        if (uGlitch > 0.0) {
          float band = floor(p.y * 1.6 + uSeed);
          float r = h(band * 12.9898 + uSeed);
          if (r > 0.72) p.x += (h(band + uSeed * 3.1) - 0.5) * 9.0 * uGlitch;
        }
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        gl_Position = projectionMatrix * mv;
        vDepth = clamp(-mv.z / 40.0, 0.0, 1.0);
        // a slow wave of light that sweeps across the flock (direction, speed and strength differ every start)
        float w = 0.5 + 0.5 * sin(dot(p.xy, uShimmerDir) * 0.22 + p.z * 0.1 - uTime * 0.55 + uPhase);
        vShine = pow(w, 10.0) * uShimmer;
        vSeed = aSeed;
        vTask = aTask;
        float flick = 0.75 + 0.25 * sin(uTime * (3.0 + aSeed * 6.0) + aSeed * 40.0);
        // neural sparks while thinking: a few particles fire white-hot, at random, never in step
        float phase = fract(aSeed * 91.7 + uTime * (0.35 + aSeed * 0.9));
        vSpark = uThink * smoothstep(0.965, 1.0, phase);
        float size = (2.0 + aSeed * 1.8) * flick * (1.0 + uBreath * 0.18 + uVoice * 0.9 + vSpark * 2.2);
        gl_PointSize = size * uPixel * (22.0 / -mv.z);
      }
    `,
    fragmentShader: /* glsl */ `
      uniform float uThreat, uVoice, uSplit;
      uniform vec3 uTaskCol[4];
      uniform vec3 uTint;
      varying float vShine;
      varying float vTask;
      varying float vSeed;
      varying float vDepth;
      varying float vSpark;
      void main() {
        vec2 c = gl_PointCoord - 0.5;
        float d = dot(c, c);
        if (d > 0.25) discard;
        float a = smoothstep(0.25, 0.0, d);
        vec3 ember = mix(vec3(1.0, 0.42, 0.08), vec3(1.0, 0.68, 0.25), vSeed);
        vec3 blood = mix(vec3(0.85, 0.02, 0.05), vec3(1.0, 0.12, 0.10), vSeed);
        vec3 col = mix(ember * uTint, blood, uThreat);
        col = mix(col, vec3(1.0, 0.86, 0.6), vShine * (1.0 - uThreat));
        if (vTask > -0.5 && uSplit > 0.0) {
          // a task's cluster wears that task's colour
          vec3 tc = vTask < 0.5 ? uTaskCol[0] : vTask < 1.5 ? uTaskCol[1] : vTask < 2.5 ? uTaskCol[2] : uTaskCol[3];
          col = mix(col, tc * (0.7 + 0.5 * vSeed), uSplit * 0.82 * (1.0 - uThreat * 0.6));
        }
        col = mix(col, vec3(1.0, 0.93, 0.8), vSpark);
        col *= 1.0 + uVoice * 0.6;
        gl_FragColor = vec4(col, a * (0.7 - vDepth * 0.4) * (1.0 + vSpark));
      }
    `,
  });
  const points = new THREE.Points(geo, mat);
  scene.add(points);

  // --- ribbons ---
  const ctrl: THREE.Vector3[][] = [];
  for (let g = 0; g < MAX_GROUPS; g++) ctrl.push(Array.from({ length: CTRL }, () => new THREE.Vector3()));
  let groups = 1 + Math.floor(rnd() * 3);
  let nextEvent = 6 + rnd() * 8;
  let shuffle = 0;
  let energy = 0;
  let lastSeed = -1;
  let mode: SwarmMode = "idle";
  let shapeMode: SwarmMode = "think"; // the last active shape, kept while it dissolves back to idle
  let morph = 0; // 0 = free murmuration, 1 = fully in the mode's shape
  let think = 0;
  let voice = 0;
  let voiceSmooth = 0;
  let mic = 0;
  let micSmooth = 0;
  const shape = new THREE.Vector3();
  let tasks: SwarmTask[] = [];
  let split = 0; // 0 = one body, 1 = fully split into task clusters
  const slotIndex = new Int8Array(TASK_RGB.length).fill(-1); // slot -> position in `tasks`
  const anchors = TASK_RGB.map(() => new THREE.Vector3());
  const proj = new THREE.Vector3();

  function placeAnchors(t: number) {
    const n = Math.min(4, Math.max(2, tasks.length));
    const squeeze = Number.isFinite(camera.aspect) ? Math.min(1, camera.aspect / 1.78) : 1;
    for (let k = 0; k < tasks.length && k < 4; k++) {
      const [x, y] = LAYOUT[n][k];
      anchors[k].set(x * squeeze + Math.cos(t * 0.5 + k * 2.1) * 0.5, y + Math.sin(t * 0.62 + k * 1.7) * 0.55, Math.sin(t * 0.4 + k) * 0.8);
    }
  }

  function reassign() {
    shuffle += 1;
    for (let i = 0; i < N; i++) {
      // most particles stay with their neighbours; a few defect - like real murmurations
      grp[i] = Math.floor(hash(i * 0.731 + shuffle * 17.3 + Math.floor(u[i] * 3) * 5.1 + S) * groups);
    }
  }
  reassign();

  // --- figures: now and then, while idle, the flock gathers into a shape and lets it go again ---
  type Form = { kind: FormKind; start: number; rise: number; hold: number; fall: number; size: number; pace: number;
    rot: THREE.Matrix4; end?: number };
  let form: Form | null = null;
  let lastKind: FormKind | null = null;
  const reduced = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  function startForm(t: number, kind?: FormKind) {
    const pool = FORMS.filter((k) => k !== lastKind);
    const k = kind ?? pool[Math.floor(rnd() * pool.length)];
    lastKind = k;
    const e = new THREE.Euler((rnd() - 0.5) * 1.3, rnd() * TAU, (rnd() - 0.5) * 0.9);
    // flat figures turn only so far that they never show their thin edge to the camera
    if (k === "torus" || k === "galaxy") e.set((rnd() - 0.5) * 1.1, (rnd() - 0.5) * 1.1, rnd() * TAU);
    if (k === "vmark") e.set((rnd() - 0.5) * 0.3, (rnd() - 0.5) * 0.8, (rnd() - 0.5) * 0.2); // the V stays upright
    form = { kind: k, start: t, rise: 1.1 + rnd() * 1.2, hold: 2.5 + rnd() * 4.5, fall: 1.5 + rnd() * 1.8,
      size: 0.75 + rnd() * 0.45, pace: rnd() < 0.5 ? -1 : 1, rot: new THREE.Matrix4().makeRotationFromEuler(e) };
  }
  function formMix(t: number): number {
    if (!form) return 0;
    const f = form;
    const x = t - f.start;
    const ease = (v: number) => v * v * (3 - 2 * v);
    let m = x < f.rise ? ease(Math.min(1, x / f.rise)) : x < f.rise + f.hold ? 1 : 1 - ease(Math.min(1, (x - f.rise - f.hold) / f.fall));
    if (f.end !== undefined) m = Math.min(m, 1 - Math.min(1, (t - f.end) / 0.6)); // Vaelon got busy: let go quickly
    if (x > f.rise + f.hold + f.fall || (f.end !== undefined && t - f.end > 0.6)) {
      form = null;
      return 0;
    }
    return m;
  }
  // the very first moments: most starts assemble a figure right after the entrance (which one: random)
  if (!reduced && !compact && rnd() < 0.7) startForm(1.2 + rnd() * 1.5);
  let nextForm = 22 + rnd() * 30;

  const p0 = new THREE.Vector3(), p1 = new THREE.Vector3(), p2 = new THREE.Vector3(), p3 = new THREE.Vector3();
  const fig = new THREE.Vector3();
  const target = new THREE.Vector3();
  const mouse = new THREE.Vector2();
  const onMouse = (e: PointerEvent) => {
    const x = (e.clientX / (window.innerWidth || 1)) * 2 - 1, y = (e.clientY / (window.innerHeight || 1)) * 2 - 1;
    if (Number.isFinite(x) && Number.isFinite(y)) mouse.set(x, y);
  };
  window.addEventListener("pointermove", onMouse);

  const clock = new THREE.Clock();
  let simT = 0;
  let raf = 0;
  let disposed = false;

  // performance governor: fewer particles on slow machines, 30 fps while the model works (frees CPU for it)
  let active = N;
  let frameCost = 0;
  let frames = 0;
  let lastRender = 0;

  function step(now: number) {
    if (disposed) return;
    raf = requestAnimationFrame(step);
    if (document.hidden) return;
    if (vw < 2 || vh < 2) return; // minimised / zero-size: nothing to show, nothing to compute
    if (!renderer || (lostAt && now - lostAt > 3000)) {
      if (now < retryAt) return; // the sky behind stays visible meanwhile
      retryAt = now + 3000;
      dropRenderer();
      lostAt = 0;
      renderer = makeRenderer();
      if (!renderer) return;
      clock.getDelta(); // no jump after the pause
    }
    if (lostAt) {
      if (drawing || !fallbackReason) setFallback("the graphics context was lost (low memory or a GPU reset)");
      return; // the browser may still give the context back by itself
    }
    if (!drawing) setFallback("");
    if (energy > 0.5 && now - lastRender < 33) return;
    lastRender = now;
    const t0 = performance.now();
    const dt = Math.min(clock.getDelta(), 1 / 20);
    simT += dt; // the swarm's own clock: on a slow machine (few frames) everything slows down together, so an
    const t = simT; // entrance or a figure never runs out before the particles get there
    const tw = t + tShift; // the wandering paths' own clock: a different stretch of them every start
    const speed = 1 + energy * 1.6;
    // damping per SECOND, not per frame: 0.965 a frame at 60 fps. Per frame, a slow machine (20-30 fps) damped far less
    // and every glitch kick flung the particles out of view for seconds.
    const damp = Math.pow(0.965, dt * 60);

    if (t > nextEvent) {
      // split, merge or re-form: never on a fixed beat
      const r = rnd();
      groups = r < 0.3 ? 1 : r < 0.65 ? 2 : r < 0.88 ? 3 : 4;
      reassign();
      nextEvent = t + 5 + rnd() * 14;
    }
    const busy = mode !== "idle" || tasks.length >= 2;
    if (form && busy && form.end === undefined) form.end = t;
    if (!form && !busy && !reduced && !compact && t > nextForm) {
      if (rnd() < 0.65) startForm(t); // not every time: sometimes the flock just keeps flying
      nextForm = t + 18 + rnd() * 45;
    }
    const fm = formMix(t);
    const f = form;

    for (let g = 0; g < groups; g++) {
      const centre = wander(g * 9.7 + 1 + S, tw * speed, p0, 3.2).clone();
      for (let k = 0; k < CTRL; k++) {
        wander(g * 31.1 + k * 4.3 + S, tw * speed * 1.3, ctrl[g][k], 8 + 2.5 * Math.sin(tw * 0.07 + g));
        ctrl[g][k].multiplyScalar(0.62).add(centre);
      }
    }

    const thick = 1.7 + Math.sin(t * 0.11) * 0.8;
    const pull = 2.6 + energy * 1.8 + morph * 1.4;
    const wantMorph = mode === "idle" ? 0 : mode === "speak" ? 0.85 : mode === "listen" ? 0.7 : 0.75;
    morph += (wantMorph - morph) * Math.min(1, dt * 1.6);
    think += ((mode === "think" || mode === "tool" ? 1 : 0) - think) * Math.min(1, dt * 3);
    voiceSmooth += (voice - voiceSmooth) * Math.min(1, dt * 14);
    const breath = 0.5 + 0.5 * Math.sin(t * 0.9);
    const spin = t * (mode === "tool" ? 2.4 : 1.4);
    micSmooth += (mic - micSmooth) * Math.min(1, dt * 12);
    const splitting = tasks.length >= 2;
    split += ((splitting ? 1 : 0) - split) * Math.min(1, dt * 2.2);
    if (splitting) placeAnchors(t);
    const cs = CLUSTER_SCALE[Math.min(4, Math.max(2, tasks.length))];
    for (let i = 0; i < active; i++) {
      const g = grp[i] % groups;
      const cp = ctrl[g];
      const s = ((u[i] + t * 0.015 * speed) % 1) * (CTRL - 3);
      const k = Math.floor(s);
      catmull(cp[k], cp[k + 1], cp[k + 2], cp[k + 3], s - k, target);
      const w = Math.sin(Math.PI * (s / (CTRL - 3))) * thick + 0.4; // thicker in the middle
      const i3 = i * 3;
      target.x += off[i3] * w;
      target.y += off[i3 + 1] * w;
      target.z += off[i3 + 2] * w;
      const sl = slotOf[i];
      const ki = sl >= 0 ? slotIndex[sl] : -1;
      if (ki >= 0 && split > 0.01) {
        // this particle works for one task: it lives in that task's own cluster
        const sd = seedAttr[i];
        const tm = tasks[ki].mode;
        if (tm === "tool") {
          const ring = i % 3;
          const R = 3.2 + ring * 2.1;
          const ang = u[i] * TAU + t * 2.4 * (ring % 2 ? -1 : 1) * (1.2 - ring * 0.25);
          const tilt = ring * 1.05 + t * 0.2 + ki;
          const x = Math.cos(ang) * R, y = 0.25, z = Math.sin(ang) * R;
          shape.set(x, y * Math.cos(tilt) - z * Math.sin(tilt), y * Math.sin(tilt) + z * Math.cos(tilt));
        } else if (tm === "wait") {
          // queued: a quiet, slowly turning shell
          const ox = off[i3], oy = off[i3 + 1] / 0.35, oz = off[i3 + 2];
          const len = Math.hypot(ox, oy, oz) || 1;
          const a = t * 0.2 + ki;
          const x = (ox / len) * 5.5, z = (oz / len) * 5.5;
          shape.set(x * Math.cos(a) - z * Math.sin(a), (oy / len) * 5.5, x * Math.sin(a) + z * Math.cos(a));
        } else {
          // thinking: its own tilted vortex, each cluster leaning a different way
          const R = 3 + sd * 6.5;
          const ang = u[i] * TAU + t * 1.4 * (1.6 / (0.6 + sd)) * (ki % 2 ? -1 : 1);
          const lift = (sd - 0.5) * 2.2 * Math.sin(ang * 2 + t);
          const tilt = 0.55 + Math.sin(t * 0.3 + ki * 1.9) * 0.35 + ki * 0.4;
          const x = Math.cos(ang) * R, y = lift, z = Math.sin(ang) * R;
          shape.set(x, y * Math.cos(tilt) - z * Math.sin(tilt), y * Math.sin(tilt) + z * Math.cos(tilt));
        }
        shape.multiplyScalar(cs).add(anchors[ki]);
        target.lerp(shape, split * 0.94);
      } else if (morph > 0.01) {
        const sd = seedAttr[i];
        if (shapeMode === "listen") {
          // listening: a wide dish that ripples with your voice
          const ang = u[i] * TAU + t * 0.25;
          const R = 5 + sd * 4 + micSmooth * 2.2 * Math.sin(u[i] * TAU * 3 - t * 7);
          const y = Math.sin(ang * 4 - t * 3) * (0.2 + micSmooth * 1.8) + (sd - 0.5) * 0.5;
          const tilt = 1.05;
          const x = Math.cos(ang) * R, z = Math.sin(ang) * R;
          shape.set(x, y * Math.cos(tilt) - z * Math.sin(tilt), y * Math.sin(tilt) + z * Math.cos(tilt));
        } else if (shapeMode === "speak") {
          // a breathing core whose surface swells with every syllable
          const r = 3.6 + voiceSmooth * 3.2 + Math.sin(t * 2 + sd * 12) * 0.35;
          const ox = off[i3], oy = off[i3 + 1] / 0.35, oz = off[i3 + 2];
          const len = Math.hypot(ox, oy, oz) || 1;
          const rr = r * (0.55 + 0.45 * Math.pow(len, 0.3));
          const a = t * 0.35;
          const x = (ox / len) * rr, z = (oz / len) * rr;
          shape.set(x * Math.cos(a) - z * Math.sin(a), (oy / len) * rr, x * Math.sin(a) + z * Math.cos(a));
        } else {
          // think: a tilted vortex; tool: three tight orbiting rings
          const ring = shapeMode === "tool" ? i % 3 : 0;
          const R = shapeMode === "tool" ? 3.2 + ring * 2.1 : 3 + sd * 6.5;
          const ang = u[i] * TAU + spin * (shapeMode === "tool" ? (ring % 2 ? -1 : 1) * (1.2 - ring * 0.25) : 1.6 / (0.6 + sd));
          const lift = shapeMode === "tool" ? 0.25 : (sd - 0.5) * 2.2 * Math.sin(ang * 2 + t);
          const tilt = shapeMode === "tool" ? ring * 1.05 + t * 0.2 : 0.55 + Math.sin(t * 0.3) * 0.25;
          const x = Math.cos(ang) * R, y = lift, z = Math.sin(ang) * R;
          shape.set(x, y * Math.cos(tilt) - z * Math.sin(tilt), y * Math.sin(tilt) + z * Math.cos(tilt));
        }
        target.lerp(shape, morph);
      } else if (mode === "idle") {
        // idle: the whole flock slowly breathes in and out
        target.multiplyScalar(0.94 + breath * 0.1);
      }
      if (f && fm > 0.004 && !(ki >= 0 && split > 0.01)) {
        // a figure: this particle's place in it, turned to the figure's random angle
        formPoint(f.kind, i, seedAttr[i], u[i], off[i3], off[i3 + 1] / 0.35, off[i3 + 2], t - f.start, f.pace, fig);
        fig.multiplyScalar(f.size).applyMatrix4(f.rot);
        target.lerp(fig, fm * 0.92 * (1 - morph));
      }
      // turbulence: breaks the outline into living edges
      const px = pos[i3], py = pos[i3 + 1], pz = pos[i3 + 2];
      if (!Number.isFinite(px + py + pz + vel[i3] + vel[i3 + 1] + vel[i3 + 2])) {
        // one bad number would stay forever (pos = pos + vel): put the particle back in the middle
        pos[i3] = pos[i3 + 1] = pos[i3 + 2] = 0;
        vel[i3] = vel[i3 + 1] = vel[i3 + 2] = 0;
        continue;
      }
      const tx = Math.sin(py * 0.35 + tw * 0.9) + Math.cos(pz * 0.31 - tw * 0.7);
      const ty = Math.sin(pz * 0.29 + tw * 0.8) + Math.cos(px * 0.33 + tw * 0.6);
      const tz = Math.sin(px * 0.27 - tw * 0.75) + Math.cos(py * 0.37 + tw * 0.85);
      const calm = 1 - fm * 0.55; // inside a figure the turbulence settles a little, so the shape reads
      let vx = vel[i3] + ((target.x - px) * pull + tx * 1.3 * calm) * dt;
      let vy = vel[i3 + 1] + ((target.y - py) * pull + ty * 1.3 * calm) * dt;
      let vz = vel[i3 + 2] + ((target.z - pz) * pull + tz * 1.3 * calm) * dt;
      vx *= damp; vy *= damp; vz *= damp;
      vel[i3] = vx; vel[i3 + 1] = vy; vel[i3 + 2] = vz;
      pos[i3] = px + vx * dt * 4;
      pos[i3 + 1] = py + vy * dt * 4;
      pos[i3 + 2] = pz + vz * dt * 4;
    }
    posAttr.needsUpdate = true;

    // slow drifting camera with a little mouse parallax
    camera.position.x += ((Math.sin(tw * 0.05) * 6 + mouse.x * 3) - camera.position.x) * 0.02;
    camera.position.y += ((Math.cos(tw * 0.04) * 3 - mouse.y * 2) - camera.position.y) * 0.02;
    if (!Number.isFinite(camera.position.x + camera.position.y)) camera.position.set(0, 0, compact ? 30 : 26);
    camera.lookAt(0, 0, 0);

    mat.uniforms.uTime.value = t;
    mat.uniforms.uThink.value = think;
    mat.uniforms.uVoice.value = Math.max(voiceSmooth, mode === "listen" ? micSmooth * 0.7 : 0);
    mat.uniforms.uSplit.value = split;
    mat.uniforms.uBreath.value = mode === "idle" ? breath : 0;
    renderer.render(scene, camera);

    frameCost += performance.now() - t0;
    if (++frames === 60) {
      const avg = frameCost / 60;
      if (avg > 12 && active > 2000) active = Math.floor(active * 0.8);
      else if (avg < 5 && active < N) active = Math.min(N, Math.floor(active * 1.15));
      geo.setDrawRange(0, active);
      frames = 0;
      frameCost = 0;
    }
  }
  raf = requestAnimationFrame(step);

  const onResize = () => {
    const w = container.clientWidth, h = container.clientHeight;
    vw = w; vh = h;
    if (w < 2 || h < 2) return; // keep the last good projection; the frame loop waits until there is a size again
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer?.setSize(w, h);
  };
  window.addEventListener("resize", onResize);
  const sizeWatch = typeof ResizeObserver !== "undefined" ? new ResizeObserver(onResize) : null;
  sizeWatch?.observe(container);

  return {
    setFx(threat, g, seed) {
      threat = c01(threat);
      g = c01(g);
      mat.uniforms.uThreat.value = threat;
      mat.uniforms.uGlitch.value = g;
      mat.uniforms.uSeed.value = seed;
      // a hard glitch makes the swarm flinch: a burst of scatter
      if (g > 0.5 && seed !== lastSeed) {
        for (let i = 0; i < N; i += 2) {
          vel[i * 3] += (hash(i + seed + S) - 0.5) * 12 * g; // a flinch, not a throw out of the window
          vel[i * 3 + 1] += (hash(i * 2 + seed + S) - 0.5) * 8 * g;
        }
      }
      lastSeed = seed;
    },
    setEnergy(e) {
      energy = c01(e);
    },
    setMode(m) {
      if (m !== mode && m !== "idle") shapeMode = m;
      mode = m;
    },
    setVoice(level) {
      voice = c01(level);
    },
    pulse(strength = 1) {
      if (!Number.isFinite(strength)) return;
      // radial shockwave from the centre
      for (let i = 0; i < N; i += 1) {
        const i3 = i * 3;
        const x = pos[i3], y = pos[i3 + 1], z = pos[i3 + 2];
        const d = Math.hypot(x, y, z) || 1;
        const k = (6 * strength) / (0.6 + d * 0.15);
        vel[i3] += (x / d) * k;
        vel[i3 + 1] += (y / d) * k;
        vel[i3 + 2] += (z / d) * k;
      }
    },
    setTasks(next) {
      const before = tasks.filter((k) => k.slot >= 0 && k.slot < 4).map((k) => k.slot);
      tasks = next.filter((k) => k.slot >= 0 && k.slot < 4).slice(0, 4).sort((a, b) => a.slot - b.slot);
      slotIndex.fill(-1);
      tasks.forEach((k, idx) => (slotIndex[k.slot] = idx));
      const now = tasks.map((k) => k.slot);
      let changed = false;
      if (now.length < 2) {
        // one task or none: the clusters flow back into a single body
        for (let i = 0; i < N; i++) if (slotOf[i] !== -1) { slotOf[i] = -1; changed = true; }
      } else {
        const n = now.length;
        const wasSplit = before.length >= 2;
        for (let i = 0; i < N; i++) {
          // matter without a living cluster joins one
          if (slotOf[i] < 0 || slotIndex[slotOf[i]] < 0) { slotOf[i] = now[Math.floor(hash(i * 3.31 + 0.7) * n) % n]; changed = true; }
        }
        for (const sNew of now) {
          if (!wasSplit || before.includes(sNew)) continue;
          // a new task: its cluster tears a share of matter out of the others
          for (let i = 0; i < N; i++) if (hash(i * 5.77 + sNew * 19.3) < 1 / n) { slotOf[i] = sNew; changed = true; }
        }
      }
      if (changed) {
        for (let i = 0; i < N; i++) taskAttrArr[i] = slotOf[i];
        taskAttr.needsUpdate = true;
      }
    },
    taskScreen(slot) {
      const ki = slot >= 0 && slot < 4 ? slotIndex[slot] : -1;
      if (ki < 0 || tasks.length < 2) return null;
      const w = container.clientWidth, h = container.clientHeight;
      proj.copy(anchors[ki]).project(camera);
      const x = (proj.x * 0.5 + 0.5) * w, y = (-proj.y * 0.5 + 0.5) * h;
      const cs = CLUSTER_SCALE[Math.min(4, Math.max(2, tasks.length))];
      proj.copy(anchors[ki]);
      proj.y -= 7 * cs;
      proj.project(camera);
      return { x, y, r: Math.abs((-proj.y * 0.5 + 0.5) * h - y) };
    },
    burst(slot) {
      const ki = slot >= 0 && slot < 4 ? slotIndex[slot] : -1;
      if (ki < 0) return;
      const c = anchors[ki];
      for (let i = 0; i < N; i++) {
        if (slotOf[i] !== slot) continue;
        const i3 = i * 3;
        const x = pos[i3] - c.x, y = pos[i3 + 1] - c.y, z = pos[i3 + 2] - c.z;
        const d = Math.hypot(x, y, z) || 1;
        const k = 9 + hash(i) * 9;
        vel[i3] += (x / d) * k;
        vel[i3 + 1] += (y / d) * k;
        vel[i3 + 2] += (z / d) * k;
      }
    },
    setMic(level) {
      mic = c01(level);
    },
    figure(kind) {
      if (kind && !FORMS.includes(kind as FormKind)) return;
      startForm(simT, kind as FormKind | undefined);
    },
    get look() {
      return { entrance, tint, seed: S, figure: form ? form.kind : null };
    },
    status() {
      return { drawing, reason: fallbackReason };
    },
    dispose() {
      disposed = true;
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("pointermove", onMouse);
      sizeWatch?.disconnect();
      geo.dispose();
      mat.dispose();
      dropRenderer();
    },
  };
}
