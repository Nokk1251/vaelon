"""Feedback from the Help page: saved as a plain text file the user can read, keep or send - nothing is sent by itself.

The note holds what the user typed plus the facts needed to understand a report (Vaelon's version, Windows version,
local or cloud model). Never a key, a name, an address, a path or a chat. When the author publishes a feedback address
(`__feedback__`), the app also offers a ready e-mail in the user's own mail program - the user still presses send.
"""
from __future__ import annotations

import platform
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from . import __feedback__, __version__

KINDS = ("idea", "problem", "question", "praise")
MAX = 5000


def clean(text) -> str:
    if not isinstance(text, str):
        raise ValueError("write something first")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text).strip()
    if not text:
        raise ValueError("write something first")
    if len(text) > MAX:
        raise ValueError(f"at most {MAX} characters")
    return text


def note(cfg, kind: str, text: str) -> str:
    """The text of the note (also the body of the e-mail)."""
    from .security import dlp

    if kind not in KINDS:
        raise ValueError("unknown kind of feedback")
    body = dlp.scrub(clean(text))  # a key pasted by mistake never reaches the file
    return (f"Vaelon feedback - {kind}\n\n{body}\n\n---\nVaelon {__version__} · Windows {platform.release()} "
            f"({platform.version()}) · model: {'local' if cfg.is_local else 'cloud'}\n")


def save(cfg, kind: str, text: str) -> dict:
    from .tools.create import out_dir

    content = note(cfg, kind, text)
    folder = out_dir(cfg) / "Feedback"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H%M%S")
    path = folder / f"Vaelon feedback {stamp}.txt"
    n = 2
    while path.exists():
        path = folder / f"Vaelon feedback {stamp} ({n}).txt"
        n += 1
    path.write_text(content, "utf-8")
    mail = (f"mailto:{__feedback__}?subject={quote(f'Vaelon feedback ({kind})')}&body={quote(content[:1800])}"
            if __feedback__ else "")
    return {"ok": True, "path": str(path), "mailto": mail}


def address() -> str:
    return __feedback__


def folder(cfg) -> Path:
    from .tools.create import out_dir

    return out_dir(cfg) / "Feedback"
