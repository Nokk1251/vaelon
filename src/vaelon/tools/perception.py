"""Perception: read any document, look at images and at the screen.

Who looks at the picture: with a LOCAL model the local vision model (ollama pull gemma3:4b) - nothing leaves the PC.
With a CLOUD model the picture is sent to that same provider (it already receives your text) - the tools say so.
Optional extras:  pip install "vaelon[docs,vision]"
"""
from __future__ import annotations

import base64
import io
from pathlib import Path

import requests

from ..security.injection import fence
from ..security.policy import Risk, resolve_path
from .registry import tool

TEXT_EXT = {".txt", ".md", ".py", ".js", ".ts", ".json", ".csv", ".log", ".html", ".xml", ".yaml", ".yml", ".ini"}


def _read_any(p: Path, limit: int) -> str:
    ext = p.suffix.lower()
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            raise RuntimeError('PDF support: pip install "vaelon[docs]"')
        reader = PdfReader(str(p))
        return "\n".join((pg.extract_text() or "") for pg in reader.pages[:60])[:limit]
    if ext == ".docx":
        try:
            import docx
        except ImportError:
            raise RuntimeError('Word support: pip install "vaelon[docs]"')
        return "\n".join(par.text for par in docx.Document(str(p)).paragraphs)[:limit]
    if ext == ".xlsx":
        try:
            import openpyxl
        except ImportError:
            raise RuntimeError('Excel support: pip install "vaelon[docs]"')
        wb = openpyxl.load_workbook(str(p), read_only=True, data_only=True)
        out = []
        for ws in wb.worksheets[:5]:
            out.append(f"# {ws.title}")
            for row in ws.iter_rows(max_row=400, values_only=True):
                if any(c is not None for c in row):
                    out.append(" | ".join("" if c is None else str(c) for c in row))
        return "\n".join(out)[:limit]
    if ext == ".pptx":
        try:
            from pptx import Presentation
        except ImportError:
            raise RuntimeError('PowerPoint support: pip install "vaelon[docs]"')
        out = []
        for n, slide in enumerate(Presentation(str(p)).slides, 1):
            texts = [sh.text_frame.text for sh in slide.shapes if sh.has_text_frame and sh.text_frame.text.strip()]
            out.append(f"# Slide {n}\n" + "\n".join(texts))
        return "\n\n".join(out)[:limit]
    if ext in TEXT_EXT or p.stat().st_size < 2_000_000:
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            return fh.read(max(1, min(limit, 400_000)))
    raise RuntimeError(f"unsupported file type {ext}")


@tool("read_document", "Read a document of any common type (pdf, docx, txt, code, csv...) - untrusted content",
      {"path": "file path", "?max_chars": "limit (default 15000)"}, untrusted=True, group="perception")
def read_document(ctx, path, max_chars=15000):
    p = resolve_path(path, ctx.cfg.allowed_roots)
    return fence(_read_any(p, int(max_chars)), f"document:{p.name}")[0]


# Cloud models that can see, per provider host (checked 2026-11-09 with a test picture). Other OpenAI-compatible
# providers: the chat model itself is tried (most current ones accept images).
CLOUD_VISION = {"groq.com": "qwen/qwen3.8-27b"}


def vision_target(cfg) -> tuple[str, str]:
    """("cloud", model) when a cloud provider will look at the picture, else ("local", model)."""
    if cfg.provider == "openai" and not cfg.is_local:
        custom = getattr(cfg, "vision_cloud_model", "")
        model = custom or next((m for host, m in CLOUD_VISION.items() if host in (cfg.base_url or "")), cfg.model)
        return "cloud", model
    return "local", cfg.vision_model


def _vision_cloud(cfg, model: str, jpeg: bytes, question: str) -> str:
    from ..llm import _key

    base = cfg.base_url or "https://api.openai.com/v1"
    r = requests.post(f"{base}/chat/completions", timeout=120, allow_redirects=False,
                      headers={"Authorization": f"Bearer {_key(cfg)}"},
                      json={"model": model, "max_tokens": 900, "temperature": 0.2, "messages": [{"role": "user", "content": [
                          {"type": "text", "text": question or "Describe what you see, precisely and briefly."},
                          {"type": "image_url", "image_url": {
                              "url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}}]}]})
    if r.status_code >= 400:
        raise RuntimeError(f"the cloud model '{model}' did not accept the picture (HTTP {r.status_code}). Set another "
                           "one with: vaelon config vision_cloud_model <name>  (see: vaelon models)")
    return r.json()["choices"][0]["message"].get("content") or ""


def _jpeg(png: bytes) -> bytes:
    from PIL import Image

    with Image.open(io.BytesIO(png)) as img:
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=85)
        return buf.getvalue()


def _vision(ctx, png: bytes, question: str) -> str:
    where, model = vision_target(ctx.cfg)
    if where == "cloud":
        return _vision_cloud(ctx.cfg, model, _jpeg(png), question)
    base = ctx.cfg.base_url if ctx.cfg.provider == "ollama" and ctx.cfg.base_url else "http://localhost:11434"
    r = requests.post(f"{base}/api/chat", timeout=300, json={
        "model": ctx.cfg.vision_model, "stream": False, "think": False, "keep_alive": "10m",
        "messages": [{"role": "user", "content": question or "Describe what you see, precisely and briefly.",
                      "images": [base64.b64encode(png).decode()]}]})
    if r.status_code == 404:
        raise RuntimeError(f"vision model missing: ollama pull {ctx.cfg.vision_model}")
    r.raise_for_status()
    return r.json()["message"]["content"]


def _png(img, max_w: int = 1280) -> bytes:
    if img.width > max_w:
        img = img.resize((max_w, int(img.height * max_w / img.width)))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    return buf.getvalue()


@tool("see_screen", "Look at the user's screen and answer a question about it (local vision model; with a cloud "
                    "model the screenshot is sent to that provider)",
      {"?question": "what to look for"}, risk=Risk.DANGEROUS, untrusted=True,
      summary=lambda a: "CAPTURE YOUR SCREEN and analyse it (with a cloud model the screenshot LEAVES this PC)",
      group="perception")
def see_screen(ctx, question=""):
    try:
        from PIL import ImageGrab
    except ImportError:
        raise RuntimeError('screen capture: pip install "vaelon[vision]"')
    emit = ctx.extra.get("emit")
    if emit:
        emit("detail", "looking at your screen")
    return fence(_vision(ctx, _png(ImageGrab.grab(), 1600), question), "screen")[0]


@tool("look_at_image", "Describe or answer a question about an image file (local vision model; with a cloud model "
                       "the image is sent to that provider)",
      {"path": "image file", "?question": "question"}, untrusted=True, group="perception")
def look_at_image(ctx, path, question=""):
    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError('images: pip install "vaelon[vision]"')
    p = resolve_path(path, ctx.cfg.allowed_roots)
    with Image.open(p) as img:
        return fence(_vision(ctx, _png(img), question), f"image:{p.name}")[0]
