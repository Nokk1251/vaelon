"""Download the local model from inside the app: Vaelon asks the user's own Ollama to pull it (Ollama's /api/pull) and
reports the progress, so nobody has to open a terminal.

- The model is always Vaelon's own choice (the configured local model, else the "local" preset). A request can never
  name another model, so nothing can make Vaelon download something else or something huge.
- One download at a time; asking again while it runs just reports the running one.
- Nothing here touches the internet itself: Ollama, on this computer (or the Ollama address in the settings), does the
  downloading from its own library.
"""
from __future__ import annotations

import json
import re
import threading
import time

import requests

NAME_RX = re.compile(r"^[a-z0-9][a-z0-9._-]{0,80}(?::[a-z0-9._-]{1,40})?$")  # e.g. qwen3:4b-instruct

_lock = threading.Lock()
_state: dict = {"running": False, "model": "", "status": "", "completed": 0, "total": 0, "error": "", "done": False,
                "started": 0.0}


def _target(cfg) -> tuple[str, str]:
    """(Ollama address, model name) - both from Vaelon's settings, never from a request."""
    from .providers import PRESETS

    base = cfg.base_url if cfg.provider == "ollama" and cfg.base_url else "http://localhost:11434"
    model = cfg.model if cfg.provider == "ollama" and cfg.model else PRESETS["local"]["model"]
    return base.rstrip("/"), model


def status() -> dict:
    with _lock:
        s = dict(_state)
    s["percent"] = round(100 * s["completed"] / s["total"], 1) if s["total"] else 0.0
    return s


def start(cfg) -> dict:
    """Begin the download in the background (or report the one that is running)."""
    base, model = _target(cfg)
    if not NAME_RX.match(model):
        return {**status(), "error": "the configured local model name is not valid"}
    with _lock:  # status() takes the same lock: never call it while holding it
        already = _state["running"]
        if not already:
            _state.update(running=True, model=model, status="starting", completed=0, total=0, error="", done=False,
                          started=time.time())
    if not already:
        threading.Thread(target=_pull, args=(base, model), daemon=True, name="vaelon-model-pull").start()
    return status()


def _pull(base: str, model: str) -> None:
    layers: dict[str, tuple[int, int]] = {}  # digest -> (completed, total): Ollama reports each part on its own
    error, finished = "", False
    try:
        with requests.post(f"{base}/api/pull", json={"model": model, "stream": True}, stream=True,
                           timeout=(5, 300)) as r:
            if r.status_code != 200:
                error = f"Ollama answered {r.status_code}"
            else:
                for line in r.iter_lines():
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        continue
                    if msg.get("error"):
                        error = str(msg["error"])[:200]
                        break
                    if msg.get("digest") and msg.get("total"):
                        layers[msg["digest"]] = (int(msg.get("completed") or 0), int(msg["total"]))
                    with _lock:
                        _state["status"] = str(msg.get("status", ""))[:120]
                        _state["completed"] = sum(c for c, _ in layers.values())
                        _state["total"] = sum(t for _, t in layers.values())
                    if msg.get("status") == "success":
                        finished = True
                        break
    except requests.RequestException as e:
        error = "Ollama is not answering" if isinstance(e, requests.ConnectionError) else f"download failed ({type(e).__name__})"
    with _lock:
        _state["running"] = False
        _state["done"] = finished and not error
        _state["error"] = error or ("" if finished else "the download stopped before it finished")
        if _state["done"]:
            _state["status"] = "success"
            _state["completed"] = _state["total"] = max(_state["total"], _state["completed"])
