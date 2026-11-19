"""1 - Intro (10 s, 1920x1080, 30 fps): Vaelon's flock flies in, splits and merges like a murmuration, then gathers
into the dotted V of the logo while part of it settles into the word VAELON.

The same flock as the app (flock.py); the V uses the real dots of brand/logo-v.webp (their sizes and colours, the
red dot included): every dot is filled by as many birds as its area needs.
Run:  blender -b --factory-startup -P logo_reveal.py -- [first] [last] [step]
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np  # noqa: E402

import flock as F  # noqa: E402
import vaelon_common as V  # noqa: E402

FPS, FRAMES = 30, 300
N = 14000
WORD_SHARE = 0.24

V.reset(1920, 1080, FPS)
cam = V.camera_fov(z=26, fov=55)
V.bloom(strength=0.4, size=6, threshold=0.9)

fl = F.Flock(N, seed=11, groups=3)
rng = np.random.default_rng(21)
cloud = V.Cloud("flock", N, subdiv=2)

# who forms what: most birds the V, some the word
word = np.zeros(N, bool)
word[rng.permutation(N)[: int(N * WORD_SHARE)]] = True
vi, wi = np.flatnonzero(~word), np.flatnonzero(word)

# the V: the logo's own dots, filled by the V birds
dxy, dr, drgb = V.load_dots("logo-v")
sub = F.Flock(len(vi), seed=5, groups=1)
v_tgt, v_col, v_dot = sub.vmark(dxy, dr, drgb, scale=6.2)
v_tgt[:, 1] += 2.2 - (dxy[:, 1].max() + dxy[:, 1].min()) / 2 * 6.2
target = np.zeros((N, 3))
target[vi] = v_tgt
tcol = np.zeros((N, 3))
tcol[vi] = v_col
# the word below it
txt = V.text_points("VAELON", len(wi), rng, spacing=1.35) * 1.55
txt[:, 1] += -7.0
target[wi] = txt
tcol[wi] = F.srgb_to_lin(np.array([1.0, 0.48, 0.12]))

# timing per bird: V birds by height (the point first, the tips last), word birds left to right
v_y = (v_tgt[:, 1] - v_tgt[:, 1].min()) / np.ptp(v_tgt[:, 1])
start = np.zeros(N)
start[vi] = 5.0 + 0.9 * v_y + rng.uniform(0, 0.35, len(vi))
w_x = (txt[:, 0] - txt[:, 0].min()) / np.ptp(txt[:, 0])
start[wi] = 6.3 + 0.9 * w_x + rng.uniform(0, 0.25, len(wi))
dur = np.where(word, 1.3, 1.5)

# the entrance: a stream from the right (one of the app's entrances)
a, b, c = rng.random(N), rng.random(N), rng.random(N)
enter = np.stack([26 + a * 24, (b - 0.5) * 10 + np.sin(a * 9) * 4, (c - 0.5) * 10], 1)
enter_t = 0.15 + a * 1.2


def update(f):
    t = f / FPS
    split = 0.6 * F.ease((t - 2.4) / 1.0) * (1 - F.ease((t - 4.2) / 0.9))      # splits, then merges again
    p = fl.murmuration(t, split=split, spread=9.0)
    # fly in from the right
    k_in = F.ease((t - enter_t) / 1.6)
    p = p + enter * (1 - k_in)[:, None]
    m = F.ease((t - start) / dur)                                          # 0 = flying, 1 = in its place
    calm = 1 - 0.88 * m
    p = fl.turbulence(p, t, amount=1.0) * calm[:, None] + p * (1 - calm)[:, None]
    # gather: a curved approach (the bird swings round on its way in)
    swing = np.sin(np.pi * m)[:, None] * np.stack([np.zeros(N), np.zeros(N), 3.0 * (fl.sd - 0.5)], 1)
    p = p * (1 - m)[:, None] + target * m[:, None] + swing
    # still alive once in place: a small shimmer, like birds holding a shape in the wind
    live = 0.05 * np.stack([np.sin(t * 2.1 + fl.sd * 40), np.cos(t * 1.7 + fl.sd * 31), np.sin(t * 1.3 + fl.sd * 17)], 1)
    p = p + live * m[:, None]
    ember = fl.colours(t, p)
    col = ember * (1 - m)[:, None] + tcol * m[:, None]
    glow = 0.9 * fl.flicker(t) * (1 - 0.45 * m)
    cloud.set(p, size=fl.size * (1 + 0.25 * m), glow=glow, col=col)
    # the camera drifts like the app's, and settles in front of the logo at the end
    settle = F.ease((t - 5.0) / 3.0)
    look = np.array([math.sin(t * 0.5) * 2.0, math.cos(t * 0.4) * 1.0, 0.0]) * (1 - settle) + np.array([0, -1.6, 0]) * settle
    at = np.array([math.sin(t * 0.3) * 5 * (1 - settle), 1.0 - 1.6 * settle, 27 - 2.5 * settle])
    V.aim(cam, tuple(at), tuple(look))


first, last, step = V.frame_args(FRAMES)
V.render_frames("logo_reveal", range(first, last + 1), update, step)
