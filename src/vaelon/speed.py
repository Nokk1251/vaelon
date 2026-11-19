"""Small things that make a spoken exchange start sooner - without sending anything new anywhere.

One keep-alive connection pool (`HTTP`) is shared by the three cloud calls of an exchange - speech-to-text, the
model, the cloud voice. Each new HTTPS connection costs a handshake of 0.1-0.3 s, and after a pause in the
conversation the services have closed the idle ones; in a row of three calls that is heard.

`warm(cfg)` is called by the app the moment you start talking or typing: it opens (or keeps open) the connections
your NEXT request will need anyway - only to services you have already chosen, with an empty request that carries
no key, no text and no audio. With the fully local setup it does nothing.
"""
from __future__ import annotations

import threading
import time
from urllib.parse import urlparse

import requests

HTTP = requests.Session()
FRESH = 20.0  # a connection used this recently is still open: nothing to do
_last: dict[str, float] = {}
_lock = threading.Lock()


def _origin(url: str) -> str:
    u = urlparse(url)
    return f"{u.scheme}://{u.netloc}" if u.scheme in ("http", "https") and u.netloc else ""


def used(url: str) -> None:
    """A real call is going to this host right now: its connection is warm for the next moments."""
    with _lock:
        _last[_origin(url)] = time.monotonic()


def targets(cfg) -> list[str]:
    """The cloud hosts the next exchange will talk to, with the current settings (none when everything is local)."""
    from . import config, stt

    out = []
    try:
        if stt.engine(cfg) == "groq":
            out.append(_origin(stt.GROQ_STT))
    except Exception:
        pass
    if not cfg.is_local:
        base = cfg.base_url or {"openai": "https://api.openai.com", "anthropic": "https://api.anthropic.com"}.get(cfg.provider, "")
        if _origin(base):
            out.append(_origin(base))
    if cfg.tts_engine == "elevenlabs" and config.env("ELEVENLABS_API_KEY"):
        from . import tts

        out.append(tts.ELEVEN)
    return list(dict.fromkeys(o for o in out if o.startswith("https://")))


def warm(cfg) -> list[str]:
    """Open the connections for the next exchange in the background. Returns the hosts being opened now."""
    now, todo = time.monotonic(), []
    with _lock:
        for origin in targets(cfg):
            if now - _last.get(origin, -1e9) > FRESH:
                _last[origin] = now
                todo.append(origin)

    def open_one(origin: str) -> None:
        try:  # no key, no body: only the TCP + TLS handshake, kept in the pool for the real request
            HTTP.head(origin + "/", timeout=4, allow_redirects=False)
        except requests.RequestException:
            with _lock:
                _last.pop(origin, None)

    for origin in todo:
        threading.Thread(target=open_one, args=(origin,), daemon=True, name="vaelon-warm").start()
    return todo
