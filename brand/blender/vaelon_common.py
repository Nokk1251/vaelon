"""Shared helpers for the Vaelon Blender pieces (Blender 5.2, EEVEE).

A "cloud" is one mesh of loose vertices; a Geometry Nodes modifier puts a small glowing sphere on every vertex.
Per vertex: `size` (radius), `col` (linear RGB colour) and `glow` (emission strength). The piece scripts move
the vertices with numpy, one frame at a time, and write PNG frames; `encode.py` turns the frames into a video.
"""
import json
import math
import os
import sys
from pathlib import Path

import bpy
import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"


# --------------------------------------------------------------------------- scene
def reset(width, height, fps=30):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x, sc.render.resolution_y = width, height
    sc.render.resolution_percentage = int(os.environ.get("VAELON_PCT", "100"))
    sc.render.fps = fps
    sc.render.film_transparent = False
    sc.eevee.taa_render_samples = int(os.environ.get("VAELON_SAMPLES", "24"))
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    try:
        sc.view_settings.view_transform = os.environ.get("VAELON_VIEW", "Standard")
    except TypeError:
        pass
    world = bpy.data.worlds.new("black")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (0, 0, 0, 1)
    bg.inputs["Strength"].default_value = 0
    sc.world = world
    return sc


def camera(z=10.0, lens=50.0, x=0.0, y=0.0, focus=None, fstop=2.8, rot=(0.0, 0.0, 0.0)):
    cam = bpy.data.cameras.new("cam")
    cam.lens = lens
    cam.clip_start, cam.clip_end = 0.05, 200
    if focus is not None:
        cam.dof.use_dof = True
        cam.dof.focus_distance = focus
        cam.dof.aperture_fstop = fstop
    ob = bpy.data.objects.new("cam", cam)
    ob.location = (x, y, z)
    ob.rotation_euler = rot
    bpy.context.scene.collection.objects.link(ob)
    bpy.context.scene.camera = ob
    return ob


def camera_fov(z=26.0, fov=55.0, x=0.0, y=0.0, look=(0.0, 0.0, 0.0), focus=None, fstop=0.2):
    """A camera like the app's: three.js PerspectiveCamera(55) at z = 26, looking at `look`."""
    cam = bpy.data.cameras.new("cam")
    cam.sensor_fit = "VERTICAL"
    cam.angle = math.radians(fov)
    cam.clip_start, cam.clip_end = 0.05, 300
    if focus is not None:
        cam.dof.use_dof = True
        cam.dof.focus_distance = focus
        cam.dof.aperture_fstop = fstop
    ob = bpy.data.objects.new("cam", cam)
    bpy.context.scene.collection.objects.link(ob)
    bpy.context.scene.camera = ob
    aim(ob, (x, y, z), look)
    return ob


def aim(ob, at, look):
    """Put the camera at `at` and point it at `look`, with +Y of the world as "up" (like three.js lookAt).
    (Vector.to_track_quat takes Blender's Z-up world as its reference and turned the picture upside down.)"""
    from mathutils import Matrix, Vector
    ob.location = at
    back = (Vector(at) - Vector(look)).normalized()          # the camera looks along its -Z
    right = Vector((0.0, 1.0, 0.0)).cross(back).normalized()
    up = back.cross(right)
    ob.rotation_euler = Matrix((right, up, back)).transposed().to_euler()


def bloom(strength=0.9, size=7, threshold=0.6):
    """Compositor: Render Layers -> Glare (bloom) -> output."""
    sc = bpy.context.scene
    nt = bpy.data.node_groups.new("comp", "CompositorNodeTree")
    nt.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    rl = nt.nodes.new("CompositorNodeRLayers")
    gl = nt.nodes.new("CompositorNodeGlare")
    out = nt.nodes.new("NodeGroupOutput")
    gl.inputs["Type"].default_value = "Bloom"
    gl.inputs["Threshold"].default_value = threshold
    gl.inputs["Strength"].default_value = strength
    gl.inputs["Size"].default_value = size
    nt.links.new(rl.outputs["Image"], gl.inputs["Image"])
    nt.links.new(gl.outputs["Image"], out.inputs[0])
    sc.compositing_node_group = nt
    sc.render.use_compositing = True


# --------------------------------------------------------------------------- clouds
def _material():
    mat = bpy.data.materials.get("ember")
    if mat:
        return mat
    # Soft, ADDITIVE dots like the app's point sprites (AdditiveBlending): light adds up where the flock is dense.
    # Transparent + Emission = pure addition; the glow fades towards the sphere's rim, so each dot looks round and soft.
    mat = bpy.data.materials.new("ember")
    mat.use_nodes = True
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "BLENDED"
    nt = mat.node_tree
    nt.nodes.clear()
    L = nt.links.new
    col = nt.nodes.new("ShaderNodeAttribute")
    col.attribute_type, col.attribute_name = "INSTANCER", "col"
    glow = nt.nodes.new("ShaderNodeAttribute")
    glow.attribute_type, glow.attribute_name = "INSTANCER", "glow"
    lw = nt.nodes.new("ShaderNodeLayerWeight")
    lw.inputs["Blend"].default_value = 0.5
    inv = nt.nodes.new("ShaderNodeMath")
    inv.operation = "SUBTRACT"
    inv.inputs[0].default_value = 1.0
    soft = nt.nodes.new("ShaderNodeMath")
    soft.operation = "POWER"
    soft.inputs[1].default_value = 2.5
    strength = nt.nodes.new("ShaderNodeMath")
    strength.operation = "MULTIPLY"
    em = nt.nodes.new("ShaderNodeEmission")
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    add = nt.nodes.new("ShaderNodeAddShader")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    L(lw.outputs["Facing"], inv.inputs[1])
    L(inv.outputs[0], soft.inputs[0])
    L(soft.outputs[0], strength.inputs[0])
    L(glow.outputs["Fac"], strength.inputs[1])
    L(col.outputs["Color"], em.inputs["Color"])
    L(strength.outputs[0], em.inputs["Strength"])
    L(tr.outputs[0], add.inputs[0])
    L(em.outputs[0], add.inputs[1])
    L(add.outputs[0], out.inputs["Surface"])
    return mat


def _cloud_nodes(subdiv):
    name = f"cloud{subdiv}"
    ng = bpy.data.node_groups.get(name)
    if ng:
        return ng
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    n = ng.nodes
    gin, gout = n.new("NodeGroupInput"), n.new("NodeGroupOutput")
    ico = n.new("GeometryNodeMeshIcoSphere")
    ico.inputs["Radius"].default_value = 1.0
    ico.inputs["Subdivisions"].default_value = subdiv
    smooth = n.new("GeometryNodeSetShadeSmooth")
    size = n.new("GeometryNodeInputNamedAttribute")
    size.data_type = "FLOAT"
    size.inputs["Name"].default_value = "size"
    inst = n.new("GeometryNodeInstanceOnPoints")
    mat = n.new("GeometryNodeSetMaterial")
    mat.inputs["Material"].default_value = _material()
    L = ng.links.new
    L(ico.outputs["Mesh"], smooth.inputs["Geometry"])
    L(gin.outputs[0], inst.inputs["Points"])
    L(smooth.outputs["Geometry"], inst.inputs["Instance"])
    L(size.outputs["Attribute"], inst.inputs["Scale"])
    L(inst.outputs["Instances"], mat.inputs["Geometry"])
    L(mat.outputs["Geometry"], gout.inputs[0])
    return ng


class Cloud:
    def __init__(self, name, n, subdiv=1):
        self.n = n
        me = bpy.data.meshes.new(name)
        me.vertices.add(n)
        me.attributes.new("size", "FLOAT", "POINT")
        me.attributes.new("glow", "FLOAT", "POINT")
        me.attributes.new("col", "FLOAT_COLOR", "POINT")
        ob = bpy.data.objects.new(name, me)
        bpy.context.scene.collection.objects.link(ob)
        mod = ob.modifiers.new("cloud", "NODES")
        mod.node_group = _cloud_nodes(subdiv)
        self.me, self.ob = me, ob

    def set(self, pos, size=None, glow=None, col=None):
        me = self.me
        me.vertices.foreach_set("co", np.ascontiguousarray(pos, dtype=np.float32).ravel())
        if size is not None:
            me.attributes["size"].data.foreach_set("value", np.broadcast_to(size, (self.n,)).astype(np.float32))
        if glow is not None:
            me.attributes["glow"].data.foreach_set("value", np.broadcast_to(glow, (self.n,)).astype(np.float32))
        if col is not None:
            c = np.ones((self.n, 4), np.float32)
            c[:, :3] = col
            me.attributes["col"].data.foreach_set("color", c.ravel())
        me.update()


# --------------------------------------------------------------------------- shapes & maths
def srgb_to_lin(c):
    c = np.asarray(c, dtype=np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def load_dots(name):
    d = json.loads((HERE / f"{name}.dots.json").read_text())
    xy = np.array([[p["x"], p["y"]] for p in d])
    r = np.array([p["r"] for p in d])
    rgb = srgb_to_lin(np.array([p["rgb"] for p in d]))
    return xy, r, rgb


def fib_sphere(n, rng=None):
    i = np.arange(n) + 0.5
    phi = np.arccos(1 - 2 * i / n)
    th = math.pi * (1 + 5 ** 0.5) * i
    p = np.stack([np.cos(th) * np.sin(phi), np.cos(phi), np.sin(th) * np.sin(phi)], 1)
    if rng is not None:
        p = p[rng.permutation(n)]
    return p


def text_points(text, n, rng, font="C:/Windows/Fonts/ariblk.ttf", spacing=1.3):
    """n random points spread evenly over the filled letters (centred, in the XY plane, 1 unit tall caps)."""
    cu = bpy.data.curves.new("txt", "FONT")
    cu.body = text
    cu.space_character = spacing
    cu.align_x, cu.align_y = "CENTER", "CENTER"
    try:
        cu.font = bpy.data.fonts.load(font)
    except RuntimeError:
        pass
    ob = bpy.data.objects.new("txt", cu)
    bpy.context.scene.collection.objects.link(ob)
    dg = bpy.context.evaluated_depsgraph_get()
    me = ob.evaluated_get(dg).to_mesh()
    me.calc_loop_triangles()
    co = np.array([v.co[:] for v in me.vertices])
    tris = np.array([t.vertices[:] for t in me.loop_triangles])
    ob.evaluated_get(dg).to_mesh_clear()
    bpy.data.objects.remove(ob)
    a, b, c = co[tris[:, 0]], co[tris[:, 1]], co[tris[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    pick = rng.choice(len(tris), n, p=area / area.sum())
    u, v = rng.random(n), rng.random(n)
    flip = u + v > 1
    u[flip], v[flip] = 1 - u[flip], 1 - v[flip]
    p = a[pick] + (b[pick] - a[pick]) * u[:, None] + (c[pick] - a[pick]) * v[:, None]
    p[:, 2] = 0
    h = p[:, 1].max() - p[:, 1].min()
    p /= h
    p -= (p.max(0) + p.min(0)) / 2
    return p


def smooth(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def ease_io(x):
    x = np.clip(x, 0, 1)
    return np.where(x < 0.5, 4 * x ** 3, 1 - (-2 * x + 2) ** 3 / 2)


def ease_back(x, s=1.7):
    x = np.clip(x, 0, 1) - 1
    return 1 + (s + 1) * x ** 3 + s * x ** 2


def rot_y(p, a):
    c, s = np.cos(a), np.sin(a)
    x, z = p[..., 0], p[..., 2]
    q = p.copy()
    q[..., 0], q[..., 2] = c * x + s * z, -s * x + c * z
    return q


def rot_x(p, a):
    c, s = np.cos(a), np.sin(a)
    y, z = p[..., 1], p[..., 2]
    q = p.copy()
    q[..., 1], q[..., 2] = c * y - s * z, s * y + c * z
    return q


# --------------------------------------------------------------------------- rendering
def args():
    """Arguments after `--`: [first_frame] [last_frame] [step]."""
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return [int(x) for x in a]


def frame_args(total):
    """`-- [first] [last] [step]` (0-based, last included) -> clamped (first, last, step). Frame `total` is never
    rendered: in a loop it equals frame 0 and would make a double frame at the seam."""
    a = args()
    first = a[0] if a else 0
    last = min(a[1] if len(a) > 1 else total - 1, total - 1)
    step = a[2] if len(a) > 2 else 1
    if not 0 <= first <= last or step < 1:
        raise SystemExit(f"bad frame range {a}: need 0 <= first <= last <= {total - 1}, step >= 1")
    return first, last, step


PNG_END = b"IEND\xaeB`\x82"


def png_ok(path, width, height):
    """A finished PNG of the expected size (a cut file or one from a smaller test render is not ok)."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(24)
            fh.seek(-12, os.SEEK_END)
            tail = fh.read()
    except OSError:
        return False
    if len(head) < 24 or not head.startswith(b"\x89PNG"):
        return False
    w, h = int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
    return (w, h) == (width, height) and tail.endswith(PNG_END)


def _check_stamp(d, name):
    """Frames made by other code or settings must not be mixed with new ones (a jump, or a seam in a loop):
    the folder keeps a fingerprint of the scripts and settings; when it changes, the old frames are removed."""
    import hashlib
    h = hashlib.sha256()
    script = Path(sys.argv[sys.argv.index("-P") + 1]) if "-P" in sys.argv else None
    for p in (script, HERE / "flock.py", HERE / "vaelon_common.py"):
        if p and Path(p).exists():
            h.update(Path(p).read_bytes())
    for k in ("VAELON_SAMPLES", "VAELON_VIEW", "VAELON_PCT"):
        h.update(f"{k}={os.environ.get(k, '')};".encode())
    h.update(name.encode())
    stamp = d / ".stamp"
    new = h.hexdigest()
    old = stamp.read_text().strip() if stamp.exists() else None
    if old != new:
        gone = list(d.glob("[0-9][0-9][0-9][0-9].png")) + list(d.glob("*.tmp.png"))
        for p in gone:
            p.unlink()
        if gone:
            print(f"[{name}] the code or settings changed: removed {len(gone)} old frames", flush=True)
        stamp.write_text(new)


def render_frames(name, frames, update, step=1):
    """Render `frames` (iterable of ints) to out/<name>/frames/0001.png ...

    A frame that already exists as a complete PNG of the current size is skipped (so a stopped render goes on
    where it was). Each frame is written to a temporary name first, then moved into place.
    """
    sc = bpy.context.scene
    test = os.environ.get("VAELON_TEST")
    d = OUT / "_test" / name if test else OUT / name / "frames"
    d.mkdir(parents=True, exist_ok=True)
    _check_stamp(d, name)
    pct = sc.render.resolution_percentage / 100
    width, height = int(sc.render.resolution_x * pct), int(sc.render.resolution_y * pct)
    for f in list(frames)[::step]:
        path = d / f"{f + 1:04d}.png"
        if png_ok(path, width, height):
            continue
        tmp = d / f"{f + 1:04d}.tmp.png"
        sc.frame_set(f)
        update(f)
        sc.render.filepath = str(tmp)
        bpy.ops.render.render(write_still=True)
        os.replace(tmp, path)
        print(f"[{name}] frame {f + 1}", flush=True)
