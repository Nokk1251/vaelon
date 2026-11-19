"""Make every app icon from the dotted V (brand/logo-v.webp). Needs Pillow.

    python scripts/make_icons.py

Writes:
  src/vaelon/data/vaelon.ico   - Vaelon.exe, the installer and the app windows (16-256 px in one file)
  ui/web/app/favicon.ico       - browser tab
  ui/web/app/icon.png          - browser tab / shortcuts (256 px)
  ui/web/app/apple-icon.png    - home-screen icon (180 px)

The mark sits on a dark rounded tile so it stays readable on light and dark taskbars. Small sizes get a tighter
crop and slightly thicker dots, otherwise the thin tips of the V disappear at 16 px.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "brand" / "logo-v.webp"
ICO = ROOT / "src" / "vaelon" / "data" / "vaelon.ico"
WEB = ROOT / "ui" / "web" / "app"
TILE = (5, 3, 4)        # the app background, #050304
EDGE = (58, 30, 10)     # faint warm outline so the tile does not vanish on a black taskbar
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
SCALE = 4               # draw big, shrink once: smooth edges


def _mark() -> Image.Image:
    """The V alone: cropped to its dots, on transparency (alpha = brightness of the black-background original)."""
    rgb = Image.open(SOURCE).convert("RGB")
    r, g, b = rgb.split()
    alpha = ImageChops.lighter(ImageChops.lighter(r, g), b).point(lambda v: 0 if v < 24 else min(255, int(v * 1.25)))
    box = alpha.getbbox()
    mark = rgb.copy()
    mark.putalpha(alpha)
    return mark.crop(box)


def render(size: int, mark: Image.Image) -> Image.Image:
    big = size * SCALE
    small = size <= 32
    m = mark
    if small:  # thicken the dots before shrinking
        grow = 2 * round(mark.width / size * 0.22) + 1
        r, g, b, a = m.split()
        m = Image.merge("RGBA", tuple(c.filter(ImageFilter.MaxFilter(grow)) for c in (r, g, b, a)))
    pad = 0.10 if small else 0.17
    room = round(big * (1 - 2 * pad))
    k = room / max(m.size)
    m = m.resize((max(1, round(m.width * k)), max(1, round(m.height * k))), Image.LANCZOS)
    tile = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)
    radius = round(big * 0.22)
    draw.rounded_rectangle((0, 0, big - 1, big - 1), radius=radius, fill=TILE + (255,), outline=EDGE + (255,),
                           width=max(1, round(big * 0.012)))
    tile.alpha_composite(m, ((big - m.width) // 2, (big - m.height) // 2))
    return tile.resize((size, size), Image.LANCZOS)


def main() -> None:
    mark = _mark()
    images = {s: render(s, mark) for s in sorted(set(SIZES) | {180})}
    ICO.parent.mkdir(parents=True, exist_ok=True)
    ordered = [images[s] for s in sorted(SIZES, reverse=True)]
    ordered[0].save(ICO, format="ICO", append_images=ordered[1:], sizes=[(s, s) for s in sorted(SIZES, reverse=True)])
    small = [images[s] for s in (48, 32, 16)]
    small[0].save(WEB / "favicon.ico", format="ICO", append_images=small[1:], sizes=[(48, 48), (32, 32), (16, 16)])
    images[256].save(WEB / "icon.png", optimize=True)
    images[180].save(WEB / "apple-icon.png", optimize=True)
    for p in (ICO, WEB / "favicon.ico", WEB / "icon.png", WEB / "apple-icon.png"):
        print(f"{p.relative_to(ROOT)}  {p.stat().st_size} bytes")


if __name__ == "__main__":
    main()
