"""Turn out/<name>/frames/*.png into out/<name>/<name>.mp4 (H.264) with Blender's own FFmpeg.

Run:  blender -b --factory-startup -P encode.py -- <name> [fps] [loops]
`loops` > 1 repeats the frames (handy to check that a loop has no seam).
"""
import sys
from pathlib import Path

import bpy

a = sys.argv[sys.argv.index("--") + 1:]
name = a[0]
fps = int(a[1]) if len(a) > 1 else 30
loops = int(a[2]) if len(a) > 2 else 1
d = Path(__file__).resolve().parent / "out" / name
frames = sorted(p for p in (d / "frames").glob("[0-9][0-9][0-9][0-9].png"))
if not frames:
    raise SystemExit(f"no frames in {d / 'frames'}")
# how many frames each piece has: a render that stopped early must not become a short video (or a loop with a seam)
EXPECTED = {"logo_reveal": 300, "bg_loop": 600, "state_idle": 600, "state_listen": 180, "state_think": 180,
            "state_tool": 180, "state_speak": 120, "state_error": 180}
nums = [int(p.stem) for p in frames]
want = EXPECTED.get(name, max(nums))
missing = sorted(set(range(1, want + 1)) - set(nums))
if missing:  # a gap would be a jump in the video (and a seam in a loop)
    raise SystemExit(f"{name}: missing frames {missing[:20]}{' ...' if len(missing) > 20 else ''}")

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
img = bpy.data.images.load(str(frames[0]))
w, h = img.size
bpy.data.images.remove(img)
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = w, h, 100
sc.render.fps = fps
sc.view_settings.view_transform = "Standard"
ed = sc.sequence_editor_create()
strips = ed.strips if hasattr(ed, "strips") else ed.sequences
start = 1
for _ in range(loops):
    s = strips.new_image(name="f", filepath=str(frames[0]), channel=1, frame_start=start)
    for f in frames[1:]:
        s.elements.append(f.name)
    s.colorspace_settings.name = "sRGB"
    start += len(frames)
sc.frame_start, sc.frame_end = 1, start - 1
r = sc.render
r.use_sequencer = True
r.use_compositing = False
if hasattr(r.image_settings, "media_type"):  # Blender 5: pick "video" before the container
    r.image_settings.media_type = "VIDEO"
r.image_settings.file_format = "FFMPEG"
r.ffmpeg.format = "MPEG4"
r.ffmpeg.codec = "H264"
r.ffmpeg.constant_rate_factor = "MEDIUM"  # web-friendly size (particles compress badly: HIGH was 2x, PERC_LOSSLESS 3x)
r.ffmpeg.ffmpeg_preset = "GOOD"
r.ffmpeg.gopsize = fps
r.ffmpeg.audio_codec = "NONE"
out = d / (f"{name}.mp4" if loops == 1 else f"{name}_x{loops}.mp4")
r.filepath = str(out)
r.use_file_extension = False
bpy.ops.render.render(animation=True)
print("WROTE", out, w, h, sc.frame_end, "frames")
