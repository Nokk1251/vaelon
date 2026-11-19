"""Read the dot marks (logo-v.webp, logo-ring.webp) and write every dot as JSON.

Each dot: x, y in [-1, 1] (y up, centred on the mark), r (same units), rgb in 0..1 (sRGB).
Run with the normal Python (needs Pillow + numpy):  python brand/blender/extract_dots.py
"""
import json
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
BRAND = HERE.parent


def dots(path: Path, size: int = 1000, thr: int = 60):
    img = Image.open(path).convert("RGB").resize((size, size), Image.LANCZOS)
    a = np.asarray(img).astype(np.int32)
    mask = a.max(axis=2) > thr
    seen = np.zeros_like(mask)
    out = []
    h, w = mask.shape
    for y0 in range(h):
        for x0 in range(w):
            if not mask[y0, x0] or seen[y0, x0]:
                continue
            q = deque([(y0, x0)])
            seen[y0, x0] = True
            pts = []
            while q:
                y, x = q.popleft()
                pts.append((y, x))
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        q.append((ny, nx))
            if len(pts) < 6:  # specks / compression noise
                continue
            p = np.array(pts)
            cy, cx = p.mean(axis=0)
            r = np.sqrt(len(pts) / np.pi)
            col = a[p[:, 0], p[:, 1]].mean(axis=0) / 255.0
            out.append({"x": cx, "y": cy, "r": r, "rgb": [round(float(c), 4) for c in col]})
    # centre the mark and scale to [-1, 1]
    xs = np.array([d["x"] for d in out])
    ys = np.array([d["y"] for d in out])
    cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
    half = max(xs.max() - xs.min(), ys.max() - ys.min()) / 2
    for d in out:
        d["x"] = round(float((d["x"] - cx) / half), 5)
        d["y"] = round(float(-(d["y"] - cy) / half), 5)
        d["r"] = round(float(d["r"] / half), 5)
    return out


if __name__ == "__main__":
    for name in ("logo-v", "logo-ring"):
        d = dots(BRAND / f"{name}.webp")
        (HERE / f"{name}.dots.json").write_text(json.dumps(d))
        print(name, len(d), "dots")
