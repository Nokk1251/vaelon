"""Vaelon's flock, in numpy - the same idea as the app's swarm (ui/web/lib/swarm.ts), written for rendering.

The app moves thousands of particles like a murmuration: each one follows a point on one of a few invisible ribbons
whose control points wander through space; the ribbons fold, split and merge, and a turbulence field breaks every
outline. Now and then the flock gathers into a figure (the dotted V among them), and each working mode has its own
shape (listen: a rippling dish, think: a vortex with sparks, tool: three rings, speak: a pulsing core).

Here positions are computed directly from time (no velocities), so a piece can be rendered frame by frame and a loop
can close exactly: with `period` set, every time term makes a whole number of cycles per period.
No bpy in this file: it can be checked with plain Python.
"""
import math

import numpy as np

TAU = 2 * math.pi
EMBER_A = np.array([1.0, 0.42, 0.08])      # the app's ember colours (fragment shader)
EMBER_B = np.array([1.0, 0.68, 0.25])
SHINE = np.array([1.0, 0.86, 0.6])
SPARK = np.array([1.0, 0.93, 0.8])
BLOOD_A = np.array([0.85, 0.02, 0.05])
BLOOD_B = np.array([1.0, 0.12, 0.10])


def srgb_to_lin(c):
    c = np.asarray(c, dtype=np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


class Flock:
    """n particles with their fixed randoms, like the app's u / off / seed."""

    def __init__(self, n, seed=1, groups=3, ctrl=6):
        self.n, self.groups, self.ctrl = n, groups, ctrl
        rng = np.random.default_rng(seed)
        self.rng = rng
        self.u = rng.random(n)                                   # place along its ribbon
        th = rng.random(n) * TAU
        ph = np.arccos(2 * rng.random(n) - 1)
        r = rng.random(n) ** 0.6
        # offset from the ribbon's centre line; flattened in y: sheets, not tubes
        self.off = np.stack([np.sin(ph) * np.cos(th) * r, np.sin(ph) * np.sin(th) * r * 0.35, np.cos(ph) * r], 1)
        self.sd = rng.random(n)                                  # the app's aSeed
        self.grp = rng.integers(0, groups, n)
        self.alt = rng.integers(0, groups, n)                    # the group it defects to when the flock splits
        self.size = 0.030 + 0.026 * self.sd                      # world units (the app: 2 + seed * 1.8 px)
        self.flick_f = rng.integers(2, 6, n)                     # flicker: whole cycles per loop
        self.flick_p = rng.uniform(0, TAU, n)
        self.wseed = rng.uniform(0, 100, (groups, ctrl + 1, 3))  # wander seeds per ribbon control point
        self.wfreq = rng.integers(1, 3, (groups, ctrl + 1, 3))   # whole cycles per period (loops)
        self.wrate = rng.uniform(0.04, 0.11, (groups, ctrl + 1, 3))  # rad/s (free pieces, like the app's wander)
        a = rng.uniform(0, TAU)
        self.shine_dir = np.array([math.cos(a), math.sin(a)])  # a unit direction for the wave of light
        self.shine_p = rng.uniform(0, TAU)

    # ------------------------------------------------------------------ ribbons
    def _wander(self, g, k, t, scale, period):
        s = self.wseed[g, k]
        if period:
            w = TAU * self.wfreq[g, k] / period
            w2 = TAU * (self.wfreq[g, k] + 1) / period
        else:
            w = self.wrate[g, k]
            w2 = w * 2.3
        return scale * np.array([
            math.sin(t * w[0] + s[0]) + 0.45 * math.sin(t * w2[0] + s[1] * 3),
            0.55 * math.sin(t * w[1] + s[1] * 2) + 0.3 * math.cos(t * w2[1] + s[2]),
            0.8 * math.cos(t * w[2] + s[2] * 5) + 0.3 * math.sin(t * w2[2] + s[0]),
        ])

    def ribbons(self, t, period=None, spread=8.0, centre=2.0, calm=1.0):
        """Control points [groups, ctrl, 3] of closed ribbons that wander (the app: wander() * 0.62 + centre).
        calm < 1 shrinks the wandering: a short loop must make whole cycles, so its points move fast unless calmed."""
        cp = np.zeros((self.groups, self.ctrl, 3))
        for g in range(self.groups):
            c = self._wander(g, self.ctrl, t, centre * calm, period)
            for k in range(self.ctrl):
                # a loose ring of control points, each wandering on its own, so the closed ribbon folds and twists
                a = TAU * k / self.ctrl + g
                ring = np.array([math.cos(a) * spread * 0.38, math.sin(a) * spread * 0.22, math.sin(a * 2) * 1.0])
                cp[g, k] = ring + self._wander(g, k, t, spread * 0.5 * calm, period) + c
        return cp

    @staticmethod
    def _catmull_closed(cp, s):
        """Closed Catmull-Rom through cp [m, 3] at s in [0, 1) (array)."""
        m = len(cp)
        x = (s % 1.0) * m
        k = np.floor(x).astype(int)
        f = (x - k)[:, None]
        p0, p1, p2, p3 = cp[(k - 1) % m], cp[k % m], cp[(k + 1) % m], cp[(k + 2) % m]
        f2, f3 = f * f, f * f * f
        return (p0 * (-0.5 * f3 + f2 - 0.5 * f) + p1 * (1.5 * f3 - 2.5 * f2 + 1)
                + p2 * (-1.5 * f3 + 2 * f2 + 0.5 * f) + p3 * (0.5 * f3 - 0.5 * f2))

    def murmuration(self, t, period=None, split=0.0, laps=1, rate=0.015, thick=None, spread=8.0, calm=1.0):
        """Free flight. split 0..1 moves the defectors to their other ribbon (the flock splits and merges).
        In a loop, `laps` = whole turns round the ribbon per period; free pieces use `rate` (the app: 0.015/s)."""
        cp = self.ribbons(t, period, spread=spread, calm=calm)
        s = self.u + (laps * t / period if period else rate * t * 3.0)
        home = np.zeros((self.n, 3))
        away = np.zeros((self.n, 3))
        for gi in range(self.groups):
            m = self.grp == gi
            if m.any():
                home[m] = self._catmull_closed(cp[gi], s[m])
            m = self.alt == gi
            if m.any():
                away[m] = self._catmull_closed(cp[gi], s[m])
        # a defector FLIES over to its other ribbon (a smooth blend), it never jumps there
        k = self.defected(split)[:, None]
        out = home * (1 - k) + away * k
        if thick is None:
            thick = 2.4 + 0.9 * math.sin(TAU * t / period) if period else 2.4 + 0.9 * math.sin(t * 0.11)
        w = (0.55 + 0.45 * np.sin(TAU * s * 2 + self.sd * 3)) * thick + 0.4   # thicker and thinner along the ribbon
        return out + self.off * w[:, None]

    def defected(self, split):
        """0..1 per bird: how far it has moved to its other ribbon at split level 0..1 (ordered by seed, so the
        same birds go first every time; each one blends over a window of split, so nobody jumps)."""
        return ease((split * 0.5 - self.sd) / 0.15 + 0.5)

    def turbulence(self, p, t, period=None, amount=1.0):
        """The app's turbulence field, applied as a displacement (breaks every outline into living edges)."""
        if period:
            a, b, c, d, e, f = (TAU * k / period for k in (2, 1, 2, 1, 1, 2))
        else:
            a, b, c, d, e, f = 0.9, 0.7, 0.8, 0.6, 0.75, 0.85
        x, y, z = p[:, 0], p[:, 1], p[:, 2]
        tx = np.sin(y * 0.35 + t * a) + np.cos(z * 0.31 - t * b)
        ty = np.sin(z * 0.29 + t * c) + np.cos(x * 0.33 + t * d)
        tz = np.sin(x * 0.27 - t * e) + np.cos(y * 0.37 + t * f)
        return p + 0.55 * amount * np.stack([tx, ty, tz], 1)

    # ------------------------------------------------------------------ looks
    def colours(self, t, p, period=None, threat=0.0, sparks=None, tint=(1.0, 1.0, 1.0)):
        """Ember colour per particle + the slow shimmer wave of light (as in the app's shaders)."""
        sd = self.sd[:, None]
        ember = (EMBER_A * (1 - sd) + EMBER_B * sd) * np.array(tint)
        blood = BLOOD_A * (1 - sd) + BLOOD_B * sd
        col = ember * (1 - threat) + blood * threat
        tt = TAU * t / period * 1 if period else t * 0.55
        w = 0.5 + 0.5 * np.sin(p[:, :2] @ self.shine_dir * 0.22 + p[:, 2] * 0.1 - tt + self.shine_p)
        shine = (w ** 10)[:, None] * 0.35 * (1 - threat)
        col = col * (1 - shine) + SHINE * shine
        if sparks is not None:
            col = col * (1 - sparks[:, None]) + SPARK * sparks[:, None]
        # the app's colours are display (sRGB) values; Blender renders in linear light
        return srgb_to_lin(np.clip(col, 0, None))

    def flicker(self, t, period=None):
        if period:
            return 0.75 + 0.25 * np.sin(TAU * self.flick_f * t / period + self.flick_p)
        return 0.75 + 0.25 * np.sin(t * (3.0 + self.sd * 6.0) + self.sd * 40.0)

    # ------------------------------------------------------------------ figures
    def vmark(self, dots_xy, dots_r, dots_rgb, scale=6.0, fold=0.0):
        """Spread the flock over the dots of the logo V: each dot gets particles in proportion to its area,
        so the V reads as a dotted V made of the flock. Returns targets [n,3], colours [n,3], dot index [n]."""
        area = dots_r ** 2
        counts = np.floor(area / area.sum() * self.n).astype(int)
        counts[np.argsort(-area)[: self.n - counts.sum()]] += 1
        idx = np.repeat(np.arange(len(dots_r)), counts)
        idx = idx[self.rng.permutation(self.n)]
        ang = self.rng.random(self.n) * TAU
        rad = np.sqrt(self.rng.random(self.n)) * dots_r[idx] * scale * 0.92
        xy = dots_xy[idx] * scale + np.stack([np.cos(ang) * rad, np.sin(ang) * rad], 1)
        z = -fold * np.abs(dots_xy[idx, 0]) * scale + self.rng.normal(0, 0.06, self.n) * dots_r[idx] * scale * 4
        return np.column_stack([xy, z]), dots_rgb[idx], idx

    def text(self, pts_xy):
        """Targets for a set of 2D points (e.g. the letters of VAELON), z = 0."""
        return np.column_stack([pts_xy, np.zeros(len(pts_xy))])

    # ------------------------------------------------------------------ the app's mode shapes
    def shape(self, mode, t, period, level=0.0):
        """Where each particle wants to be in a working mode (whole cycles per period -> loops close)."""
        sd, u, off = self.sd, self.u, self.off
        w = TAU / period
        if mode == "listen":
            ang = u * TAU + w * t                                   # one slow turn of the dish per loop
            R = 5 + sd * 4 + level * 2.2 * np.sin(u * TAU * 3 - w * 3 * t)
            y = np.sin(ang * 4 - w * 3 * t) * (0.2 + level * 1.8) + (sd - 0.5) * 0.5
            return _tilt(np.cos(ang) * R, y, np.sin(ang) * R, 1.05)
        if mode == "speak":
            env = level
            r = 3.6 + env * 3.2 + np.sin(w * 2 * t + sd * 12) * 0.35
            o = np.column_stack([off[:, 0], off[:, 1] / 0.35, off[:, 2]])
            ln = np.linalg.norm(o, axis=1) + 1e-9
            rr = r * (0.55 + 0.45 * ln ** 0.3)
            a = w * t
            x, z = o[:, 0] / ln * rr, o[:, 2] / ln * rr
            return np.stack([x * math.cos(a) - z * math.sin(a), o[:, 1] / ln * rr, x * math.sin(a) + z * math.cos(a)], 1)
        if mode == "tool":
            ring = np.arange(self.n) % 3
            R = 3.2 + ring * 2.1
            laps = np.array([2, -2, 1])[ring]                       # the app: 1.2 / 0.95 / 0.7 turns per spin
            ang = u * TAU + w * laps * t
            tilt = ring * 1.05 + w * t                              # the rings tumble once per loop
            x, z = np.cos(ang) * R, np.sin(ang) * R
            y = np.full(self.n, 0.25)
            return np.stack([x, y * np.cos(tilt) - z * np.sin(tilt), y * np.sin(tilt) + z * np.cos(tilt)], 1)
        if mode == "think":
            R = 3 + sd * 6.5
            laps = np.where(sd < 0.33, 3, np.where(sd < 0.66, 2, 1))  # the inside spins faster, like the app
            ang = u * TAU + w * laps * t
            lift = (sd - 0.5) * 2.2 * np.sin(ang * 2 + w * t)
            tilt = 0.55 + math.sin(w * t) * 0.25
            return _tilt(np.cos(ang) * R, lift, np.sin(ang) * R, tilt)
        raise ValueError(mode)

    def sparks(self, t, period, cycles=2):
        """Neural sparks while thinking: a few particles fire white-hot, at random, never in step."""
        k = 1 + (self.sd * 3).astype(int) * cycles
        phase = (self.sd * 91.7 + k * t / period) % 1.0
        # a short bell (rises and falls), so a spark never switches off in one frame
        return ease(1 - np.abs(phase - 0.975) / 0.022)


def _tilt(x, y, z, a):
    ca, sa = np.cos(a), np.sin(a)
    return np.stack([x, y * ca - z * sa, y * sa + z * ca], 1)


def ease(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)
