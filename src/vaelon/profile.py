"""What Vaelon knows about YOU, learned automatically from what you say ("казвам се Ники", "живея във Варна").

Stored ENCRYPTED (vault, AES-256-GCM) in ~/.vaelon/profile.enc. Shown in the app's menu (Memory tab), erased with
`vaelon memory wipe`. Only facts you state about yourself are kept - nothing is inferred or sent anywhere.
"""
from __future__ import annotations

import json
import re
import threading

from . import config
from .security import vault

FILE = "profile.enc"
_lock = threading.Lock()
_CAP = r"([A-ZА-ЯЁ][\w-]{1,30})"  # a capitalised name

PATTERNS = [
    ("name", re.compile(r"(?i:казвам се|името ми е|наричай ме|аз съм|my name is|call me)\s+" + _CAP)),
    ("city", re.compile(r"(?i:живея в|живея във|аз съм от|роден съм в|i live in|i'm from|i am from)\s+"
                        r"([A-ZА-ЯЁ][\w-]{2,30}(?:\s+[A-ZА-Я][\w-]+)?)")),
    ("job", re.compile(r"(?i:работя като|по професия съм|i work as an?|i work as)\s+([\w -]{3,40}?)(?=[.,!?]|$)")),
    ("age", re.compile(r"(?i:на|i am|i'm)\s+(\d{1,2})\s*(?i:години|год\.?|years old)")),
]
LIKES = re.compile(r"(?i:харесвам|обичам|любимият ми \w+ е|любимата ми \w+ е|i like|i love|my favou?rite \w+ is)\s+"
                   r"([^.,!?\n]{3,50})")
NOT_NAMES = {"Vaelon", "Вейлон", "Добре", "Готов", "Тук"}


def _path():
    return config.HOME / FILE


def load(strict: bool = False) -> dict:
    """The profile. `strict`: a file that exists but cannot be read raises instead of looking empty (a write after an
    empty-looking read would wipe name, city, work and likes)."""
    p = _path()
    if not p.exists():
        return {}
    try:
        return json.loads(vault.decrypt_text(p.read_text("utf-8")))
    except Exception:
        if strict:
            raise
        return {}


def save(data: dict) -> None:
    import os

    config.HOME.mkdir(parents=True, exist_ok=True)
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(vault.encrypt_text(json.dumps(data, ensure_ascii=False)), "utf-8")
    vault.replace(tmp, _path())


def observe(text: str) -> dict:
    """Pick up facts the user states about themself. Returns what changed."""
    found: dict = {}
    for key, rx in PATTERNS:
        m = rx.search(text)
        if m:
            val = m.group(1).strip(" .")
            if key == "name" and val in NOT_NAMES:
                continue
            found[key] = val
    likes = [m.group(1).strip() for m in LIKES.finditer(text)]
    if not found and not likes:
        return {}
    with _lock:
        data = load(strict=True)
        changed = {k: v for k, v in found.items() if data.get(k) != v}
        data.update(found)
        if likes:
            cur = data.get("likes", [])
            new = [x for x in likes if x.lower() not in {c.lower() for c in cur}]
            if new:
                data["likes"] = (cur + new)[-20:]
                changed["likes"] = new
        if changed:
            save(data)
    return changed


LABELS_BG = {"name": "име", "city": "град", "job": "работа", "age": "възраст", "likes": "харесва"}


def summary(data: dict | None = None, lang: str = "en") -> str:
    data = load() if data is None else data
    lab = (lambda k: LABELS_BG.get(k, k)) if lang == "bg" else (lambda k: k)
    parts = [f"{lab(k)}: {v}" for k, v in data.items() if k != "likes" and v]
    if data.get("likes"):
        parts.append(lab("likes") + ": " + ", ".join(data["likes"][-8:]))
    return "; ".join(parts)


def wipe() -> None:
    _path().unlink(missing_ok=True)
