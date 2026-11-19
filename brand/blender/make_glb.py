"""4 - The V mark as a flock, for the web: out/web3d/vaelon-v.glb.

A point cloud: 6000 "birds" spread over the dots of brand/logo-v.webp (each dot gets birds in proportion to its area,
in the dot's own colour - the red dot included). The arms are folded back a little, so the V has depth when it turns.
Per point: POSITION (its place in the V), COLOR_0, and _SEED (0..1, the bird's own random, like the app's aSeed).
The web page (web3d.template.html) flies the birds in, keeps them alive and lets the pointer scare them.
Run:  blender -b --factory-startup -P make_glb.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy  # noqa: E402
import numpy as np  # noqa: E402

import flock as F  # noqa: E402
import vaelon_common as V  # noqa: E402

NAME = "vaelon-v"
N = 6000
bpy.ops.wm.read_factory_settings(use_empty=True)

xy, r, rgb = V.load_dots("logo-v")
xy = xy - (xy.max(0) + xy.min(0)) / 2
fl = F.Flock(N, seed=3, groups=1)
pos, col, _ = fl.vmark(xy, r, rgb, scale=1.0, fold=0.3)
pos[:, 2] -= pos[:, 2].mean()

# Blender 5.2's glTF exporter drops loose vertices, so every bird is a tiny triangle (its own 3 vertices);
# the web page takes each triangle's centre as the bird. In other 3D viewers the V shows as a cloud of specks.
tri = np.array([[0.0, 1.0, 0.0], [-0.87, -0.5, 0.0], [0.87, -0.5, 0.0]]) * 0.006
verts = (pos[:, None, :] + tri[None]).reshape(-1, 3)
faces = np.arange(N * 3).reshape(N, 3)
me = bpy.data.meshes.new(NAME)
me.from_pydata(verts.tolist(), [], faces.tolist())
ca = me.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
c4 = np.ones((N * 3, 4), np.float32)
c4[:, :3] = np.repeat(col, 3, axis=0)
ca.data.foreach_set("color", c4.ravel())
me.color_attributes.active_color = ca
sd = me.attributes.new("_seed", "FLOAT", "POINT")
sd.data.foreach_set("value", np.repeat(fl.sd, 3).astype(np.float32))
ob = bpy.data.objects.new("VaelonV", me)
bpy.context.scene.collection.objects.link(ob)

out = V.OUT / "web3d"
out.mkdir(parents=True, exist_ok=True)
bpy.ops.export_scene.gltf(
    filepath=str(out / f"{NAME}.glb"), export_format="GLB", export_attributes=True,
    export_vertex_color="ACTIVE", export_normals=False, export_texcoords=False, export_materials="NONE",
    export_yup=False,  # keep Blender axes: the mark faces +Z, which is where the web camera looks from
)
print("WROTE", out / f"{NAME}.glb", N, "birds")
