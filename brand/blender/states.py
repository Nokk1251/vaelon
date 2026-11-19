"""3 - Vaelon's states, as in the app (ui/web/lib/swarm.ts), each a seamless loop (720x720, 30 fps, black).

  idle    20 s  the free murmuration, breathing in and out
  listen   6 s  a wide tilted dish that ripples with your voice
  think    6 s  a tilted vortex with neural sparks (the inside spins faster)
  tool     6 s  three tight orbiting rings
  speak    4 s  a breathing core that swells with every syllable
  error    6 s  the flock flushes blood red and tears for a moment

Like the app, a working mode pulls the flock most of the way into its shape (morph 0.7-0.85) and the rest of each
bird still follows the murmuration, so the shape lives. Every time term makes a whole number of cycles per loop.
Use them on a dark page with `mix-blend-mode: screen` (black becomes transparent).
Run:  blender -b --factory-startup -P states.py -- <state|all> [step]
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np  # noqa: E402

import flock as F  # noqa: E402
import vaelon_common as V  # noqa: E402

FPS = 30
TAU = F.TAU
STATES = {"idle": 20, "listen": 6, "think": 6, "tool": 6, "speak": 4, "error": 6}
MORPH = {"listen": 0.7, "think": 0.75, "tool": 0.75, "speak": 0.85}
N = 9000                                     # the app's flock on a normal PC

V.reset(720, 720, FPS)
cam = V.camera_fov(z=26, fov=55)
V.aim(cam, (0, 0, 26), (0, 0, 0))
V.bloom(strength=0.4, size=6, threshold=0.9)
fl = F.Flock(N, seed=8, groups=2)
cloud = V.Cloud("flock", N, subdiv=2)


def voice(u, base=3):
    """A speech-like loudness 0..1 (whole cycles per loop)."""
    e = 0.55 * np.sin(TAU * base * u) + 0.3 * np.sin(TAU * (base * 2 + 1) * u + 1.1) + 0.15 * np.sin(TAU * (base * 4 - 1) * u + 2.3)
    return max(0.0, float(e)) ** 0.8


def frame(state, f, frames):
    T = frames / FPS
    t = f / FPS
    u = f / frames
    # short loops must make whole cycles, so their free flight is calmed (else it races far faster than the app)
    calm = min(1.0, T / 20.0)
    free = fl.murmuration(t, period=T, spread=8.0 if state in ("idle", "error") else 6.0, laps=1, calm=calm)
    threat, sparks, glitch = 0.0, None, 0.0
    if state in MORPH:
        level = voice(u, 3) if state in ("speak", "listen") else 0.0
        shape = fl.shape(state, t, T, level=level)
        p = free * (1 - MORPH[state]) + shape * MORPH[state]
        if state == "think":
            sparks = fl.sparks(t, T)
    else:
        breath = 0.5 + 0.5 * math.sin(TAU * 2 * u)        # idle: the whole flock slowly breathes
        p = free * (0.94 + breath * 0.1)
    if state == "error":
        pulse = math.sin(math.pi * u) ** 2                  # a red flush that comes and goes once per loop
        threat = pulse
        glitch = max(0.0, math.sin(TAU * 3 * u)) ** 6 * pulse
    p = fl.turbulence(p, t, period=T, amount=0.8 if state == "idle" else 0.55)
    if glitch > 0:
        # the app's tear: horizontal bands of the flock jump sideways
        band = np.floor(p[:, 1] * 1.6 + 7)
        r = (np.sin(band * 12.9898 + 7) * 43758.5453) % 1.0
        shift = ((np.sin(band * 3.1 + 2) * 43758.5453) % 1.0 - 0.5) * 9.0 * glitch
        p[:, 0] += np.where(r > 0.72, shift, 0.0)
    col = fl.colours(t, p, period=T, threat=threat, sparks=sparks)
    lift = 1.0
    if state == "speak":
        lift = 1 + 0.6 * voice(u, 3)                        # the app: colour * (1 + voice * 0.6)
    size = fl.size * (1 + (sparks * 1.1 if sparks is not None else 0))
    glow = 0.9 * fl.flicker(t, T) * lift * (1 + (sparks * 1.2 if sparks is not None else 0))
    cloud.set(p, size=size, glow=glow, col=col)


a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
which = a[0] if a else "all"
step = int(a[1]) if len(a) > 1 else 1
if which != "all" and which not in STATES:
    raise SystemExit(f"unknown state {which!r}; use one of: all, {', '.join(STATES)}")
for name, secs in STATES.items():
    if which not in ("all", name):
        continue
    n = secs * FPS
    V.render_frames(f"state_{name}", range(n), lambda f, s=name, fr=n: frame(s, f, fr), step)
