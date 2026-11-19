"""Make out/web3d/vaelon-3d.html: web3d.template.html with the GLB inlined (works when opened as a file).

Also writes out/web3d/index.html that loads vaelon-v.glb next to it (for a web server / the website).
Run with the normal Python after make_glb.py:  python brand/blender/build_web3d.py
"""
import base64
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out" / "web3d"
tpl = (HERE / "web3d.template.html").read_text(encoding="utf-8")
glb = (OUT / "vaelon-v.glb").read_bytes()
data = "data:model/gltf-binary;base64," + base64.b64encode(glb).decode("ascii")
(OUT / "vaelon-3d.html").write_text(tpl.replace("__GLB_URL__", data), encoding="utf-8")
(OUT / "index.html").write_text(tpl.replace("__GLB_URL__", "vaelon-v.glb"), encoding="utf-8")
print("wrote", OUT / "vaelon-3d.html", OUT / "index.html")
