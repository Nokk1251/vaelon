"""Tamper-evident local audit log (hash chain). Content is redacted; nothing leaves the machine."""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from pathlib import Path

from .. import config
from .redact import redact


def _file() -> Path:
    return config.HOME / "audit.jsonl"


def _digest(rec: dict) -> str:
    """v2 entries are chained with HMAC (key in the vault): an attacker who edits the log cannot recompute
    the chain without the key. v1 (plain SHA-256) entries from older versions still verify."""
    body = json.dumps(rec, sort_keys=True, ensure_ascii=False).encode()
    if rec.get("v") == 2:
        from . import vault

        return hmac.new(vault.subkey("audit"), body, hashlib.sha256).hexdigest()
    return hashlib.sha256(body).hexdigest()


_lock = threading.Lock()  # parallel tasks write here: one line at a time, each chained to the one before
SEALED = ("text", "summary", "args", "detail")  # what the user wrote / asked: encrypted inside the log


def _last_hash(p: Path) -> str:
    """The hash of the last good line (a line cut off by a crash or power loss is skipped, never fatal)."""
    if not p.exists():
        return "0" * 64
    window = 65536
    with p.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        while True:  # widen the window until it holds a whole line (an old line may be long)
            f.seek(max(0, size - window))
            tail = f.read().decode("utf-8", "replace").splitlines()
            if size > window:
                tail = tail[1:]  # the first line of the window may be cut
            for line in reversed(tail):
                try:
                    return json.loads(line)["hash"]
                except (ValueError, KeyError, TypeError):
                    continue
            if window >= size:
                return "0" * 64
            window *= 4


def _seal(data: dict) -> dict:
    from . import vault

    out = {}
    for k, v in data.items():
        if k in SEALED and v not in (None, ""):
            text = json.dumps(v, default=str, ensure_ascii=False)
            if len(text) > 4000:  # a whole file written by a tool: the log keeps its start and its size
                text = text[:4000] + f" ... [{len(text)} characters]"
            try:
                out[k] = "enc:" + vault.encrypt_text(text)
                continue
            except Exception:
                pass
        out[k] = v
    return out


def log(event: str, **data) -> None:
    """Never raises: the log must not be able to stop a request."""
    try:
        config.HOME.mkdir(parents=True, exist_ok=True)
        p = _file()
        safe = _seal(json.loads(redact(json.dumps(data, default=str, ensure_ascii=False), "pii")))
        with _lock:
            rec = {"v": 2, "ts": time.time(), "event": event, "data": safe, "prev": _last_hash(p)}
            rec["hash"] = _digest(rec)
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def verify() -> tuple[bool, int]:
    p = _file()
    if not p.exists():
        return True, 0
    prev, n, v2 = "0" * 64, 0, False
    for line in p.read_text("utf-8").splitlines():
        try:
            rec = json.loads(line)
            h = rec.pop("hash")
        except (ValueError, KeyError, AttributeError):
            return False, n
        if v2 and rec.get("v") != 2:
            return False, n  # an old-style (keyless) line after keyed ones: someone rewrote the log
        v2 = v2 or rec.get("v") == 2
        if rec.get("prev") != prev or _digest(rec) != h:
            return False, n
        prev, n = h, n + 1
    return True, n
