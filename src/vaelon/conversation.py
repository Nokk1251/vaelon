"""Conversations: several chats, each surviving restarts, so Vaelon remembers what you were talking about.

Everything is ENCRYPTED (vault, AES-256-GCM) in ~/.vaelon/chats:
- `<id>.enc`   one chat, one encrypted line per message, trimmed to the newest KEEP messages;
- `index.enc`  which chats exist, their titles (the first thing you asked - so encrypted too) and which is open.
One chat is "current": the agent reads and writes that one. `load`, `append`, `clear` and `count` work on it, so the
rest of Vaelon does not need to know there are several. A history written before chats existed
(~/.vaelon/conversation.enc) becomes the first chat, as it is - nothing is re-encrypted.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid

from . import config
from .security import vault

FILE = "conversation.enc"  # the single history of versions before 0.7
DIR = "chats"
KEEP = 200       # messages kept per chat
MAX_CHATS = 200  # the oldest untouched chats beyond this are removed
TITLE_LEN = 60
ID_RX = re.compile(r"[a-f0-9]{12}")
_lock = threading.RLock()


def _dir():
    return config.HOME / DIR


def path(chat: str | None = None):
    """The file of a chat (default: the current one)."""
    return _dir() / f"{chat or current()}.enc"


def _title(text: str) -> str:
    text = re.sub(r"\[Attached file: [^\]]*\]", "", text or "")
    return re.sub(r"\s+", " ", text).strip()[:TITLE_LEN]


def _read_lines(p) -> list[str]:
    return p.read_text("utf-8").splitlines() if p.exists() else []


def _care(m: dict) -> dict:
    """The outside-content mark of an answer and the addresses its tools returned (see Agent._turn_done)."""
    if not m.get("tainted"):
        return {}
    urls = [u for u in (m.get("urls") or []) if isinstance(u, str) and len(u) <= 2000][:50]
    return {"tainted": True, **({"urls": urls} if urls else {})}


def _decode(lines: list[str]) -> list[dict]:
    out = []
    for line in lines:
        try:
            m = json.loads(vault.decrypt_text(line, allow_plain=True))
            if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str):
                out.append({"role": m["role"], "content": m["content"], **_care(m)})
        except Exception:
            continue  # damaged or foreign line: skip it
    return out


def _index() -> dict:
    """{"current": id, "chats": {id: {"title", "created", "updated", "count"}}} - created on first use."""
    p = _dir() / "index.enc"
    data = None
    if p.exists():
        try:
            data = json.loads(vault.decrypt_text(p.read_text("utf-8").strip()))
        except Exception:
            data = None
    dirty = False
    if not isinstance(data, dict) or not isinstance(data.get("chats"), dict):
        data, dirty = {"current": "", "chats": {}}, True
        for f in sorted(_dir().glob("*.enc")) if _dir().is_dir() else []:  # an unreadable index: keep the chats
            if ID_RX.fullmatch(f.stem):
                msgs = _decode(_read_lines(f))
                first = next((m["content"] for m in msgs if m["role"] == "user"), "")
                data["chats"][f.stem] = {"title": _title(first), "created": f.stat().st_mtime,
                                         "updated": f.stat().st_mtime, "count": len(msgs)}
        old = config.HOME / FILE
        if old.exists():  # the history of an earlier version becomes the first chat
            cid = uuid.uuid4().hex[:12]
            _dir().mkdir(parents=True, exist_ok=True)
            old.replace(_dir() / f"{cid}.enc")
            msgs = _decode(_read_lines(_dir() / f"{cid}.enc"))
            first = next((m["content"] for m in msgs if m["role"] == "user"), "")
            now = time.time()
            data["chats"][cid] = {"title": _title(first), "created": now, "updated": now, "count": len(msgs)}
            data["current"] = cid
    if data.get("current") not in data["chats"]:
        newest = sorted(data["chats"], key=lambda c: data["chats"][c].get("updated", 0))
        data["current"] = newest[-1] if newest else _new_in(data)
        dirty = True
    if dirty:
        _save(data)  # built or repaired just now: the same answer next time
    return data


def _save(data: dict) -> None:
    _dir().mkdir(parents=True, exist_ok=True)
    tmp = _dir() / "index.tmp"
    tmp.write_text(vault.encrypt_text(json.dumps(data, ensure_ascii=False)), "utf-8")
    vault.replace(tmp, _dir() / "index.enc")


def _new_in(data: dict) -> str:
    cid = uuid.uuid4().hex[:12]
    now = time.time()
    data["chats"][cid] = {"title": "", "created": now, "updated": now, "count": 0}
    data["current"] = cid
    return cid


# ---------------------------------------------------------------- the current chat (what the agent uses)

def current() -> str:
    with _lock:
        return _index()["current"]


def load(n: int = 12) -> list[dict]:
    with _lock:
        return _decode(_read_lines(path())[-n:])


def append(messages: list[dict]) -> None:
    lines = [vault.encrypt_text(json.dumps({"role": m["role"], "content": m["content"][:4000], **_care(m)},
                                           ensure_ascii=False))
             for m in messages]
    with _lock:
        data = _index()
        cid = data["current"]
        _dir().mkdir(parents=True, exist_ok=True)
        p = _dir() / f"{cid}.enc"
        with p.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        old = _read_lines(p)
        if len(old) > KEEP * 1.5:
            old = old[-KEEP:]
            p.write_text("\n".join(old) + "\n", "utf-8")
        meta = data["chats"][cid]
        if not meta.get("title"):
            meta["title"] = _title(next((m["content"] for m in messages if m["role"] == "user"), ""))
        meta["updated"], meta["count"] = time.time(), len(old)
        _save(data)


def clear() -> None:
    """Erase the messages of the current chat (the chat itself stays, empty and untitled)."""
    with _lock:
        data = _index()
        path(data["current"]).unlink(missing_ok=True)
        data["chats"][data["current"]].update(title="", count=0, updated=time.time())
        _save(data)


def count() -> int:
    with _lock:
        return len(_read_lines(path()))


# ---------------------------------------------------------------- the list of chats

def chats() -> list[dict]:
    """Every chat, newest first: {id, title, updated, count, current}."""
    with _lock:
        data = _index()
        rows = [{"id": cid, "title": m.get("title", ""), "updated": m.get("updated", 0), "count": m.get("count", 0),
                 "current": cid == data["current"]} for cid, m in data["chats"].items()]
    return sorted(rows, key=lambda r: r["updated"], reverse=True)


def new() -> str:
    """Start a fresh chat and make it current. An empty current chat is reused instead of piling up blanks."""
    with _lock:
        data = _index()
        if data["chats"][data["current"]].get("count", 0) == 0:
            return data["current"]
        cid = _new_in(data)
        stale = sorted(data["chats"], key=lambda c: data["chats"][c].get("updated", 0))[:-MAX_CHATS]
        for old in stale:
            if old != cid:
                path(old).unlink(missing_ok=True)
                data["chats"].pop(old, None)
        _save(data)
        return cid


def open_chat(chat: str) -> bool:
    with _lock:
        data = _index()
        if chat not in data["chats"]:
            return False
        data["current"] = chat
        _save(data)
        return True


def delete(chat: str) -> bool:
    """Remove a chat for good. Deleting the open one opens the newest remaining chat (or a fresh one)."""
    with _lock:
        data = _index()
        if chat not in data["chats"] or not ID_RX.fullmatch(chat):
            return False
        path(chat).unlink(missing_ok=True)
        del data["chats"][chat]
        if data["current"] == chat:
            rest = sorted(data["chats"], key=lambda c: data["chats"][c].get("updated", 0))
            data["current"] = rest[-1] if rest else _new_in(data)
        _save(data)
        return True


def rename(chat: str, title: str) -> bool:
    with _lock:
        data = _index()
        if chat not in data["chats"] or not _title(title):
            return False
        data["chats"][chat]["title"] = _title(title)
        _save(data)
        return True


def messages(chat: str, n: int = KEEP) -> list[dict] | None:
    """The messages of a chat for showing it again (None: no such chat)."""
    with _lock:
        if chat not in _index()["chats"] or not ID_RX.fullmatch(chat):
            return None
        return _decode(_read_lines(path(chat))[-n:])


def wipe() -> None:
    """Erase every chat (`vaelon memory wipe`)."""
    with _lock:
        for f in list(_dir().glob("*")) if _dir().is_dir() else []:
            f.unlink(missing_ok=True)
        (config.HOME / FILE).unlink(missing_ok=True)
