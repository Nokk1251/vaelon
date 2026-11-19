"""2 - Seamless background loop (20 s, 1920x1080, 30 fps): Vaelon's murmuration flying free.

The flock follows three wandering ribbons, splits into groups and merges again, with the turbulence and the light
wave of the app. Every time term makes a whole number of cycles per 20 s, so frame 600 == frame 0.
Run:  blender -b --factory-startup -P bg_loop.py -- [first] [last] [step]
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np  # noqa: E402

import flock as F  # noqa: E402
import vaelon_common as V  # noqa: E402

FPS, SECONDS = 30, 20
FRAMES, T = FPS * SECONDS, float(SECONDS)
N = 14000

V.reset(1920, 1080, FPS)
cam = V.camera_fov(z=26, fov=55)
V.bloom(strength=0.4, size=6, threshold=0.9)

fl = F.Flock(N, seed=4, groups=3)
cloud = V.Cloud("flock", N, subdiv=2)
GLOW = 0.9


def update(f):
    t = f / FPS
    split = 0.5 - 0.5 * math.cos(F.TAU * t / T)            # one split + merge per loop
    p = fl.murmuration(t, period=T, split=split, spread=11.0)
    p = fl.turbulence(p, t, period=T)
    p[:, 1] *= 0.9
    col = fl.colours(t, p, period=T)
    cloud.set(p, size=fl.size, glow=GLOW * fl.flicker(t, T), col=col)
    # the app's slow drifting camera, closed into one sway per loop
    a = F.TAU * t / T
    look = tuple(0.6 * p.mean(0))                           # keep the flock in frame (periodic, like p)
    V.aim(cam, (math.sin(a) * 5 + look[0], math.cos(a) * 2.5 - 1.3 + look[1], 26), look)


first, last, step = V.frame_args(FRAMES)
V.render_frames("bg_loop", range(first, last + 1), update, step)
