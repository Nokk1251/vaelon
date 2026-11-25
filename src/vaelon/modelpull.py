"""Download the local model from inside the app: Vaelon asks the user's own Ollama to pull it (Ollama's /api/pull) and
reports the progress, so nobody has to open a terminal.

- The model is the configured local model (else the "local" preset's), or one the user picked from Vaelon's curated
  list (localmodels.NAMES) - a request can name no other, so nothing can make this download something unexpected.
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

# e.g. qwen3:4b-instruct, llama3.1:8b-instruct-q4_K_M, user/model:tag, hf.co/user/model (only ever sent as JSON)
NAME_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}(?:/[A-Za-z0-9._-]{1,80}){0,2}(?::[A-Za-z0-9._-]{1,80})?\Z")  # \Z: "$" would also allow a newline at the end

_lock = threading.Lock()
_state: dict = {"running": False, "model": "", "status": "", "completed": 0, "total": 0, "error": "", "done": False,
                "started": 0.0}


def _target(cfg, choice: str | None = None) -> tuple[str, str]:
    """(Ollama address, model name). The model is Vaelon's own setting, or - when the user picks one in the app - a
    model from the curated list (localmodels.CATALOG). A request can never name anything else."""
    from .localmodels import NAMES
    from .providers import PRESETS

    base = cfg.base_url if cfg.provider == "ollama" and cfg.base_url else "http://localhost:11434"
    model = cfg.model if cfg.provider == "ollama" and cfg.model else PRESETS["local"]["model"]
    if choice and choice in NAMES:
        model = choice
    return base.rstrip("/"), model


def status(cfg=None, choice: str | None = None) -> dict:
    """The download's state. With `cfg`: an earlier, finished download of ANOTHER model is not reported as this one
    (the one Vaelon is set to use, or `choice` from the curated list)."""
    with _lock:
        s = dict(_state)
    if cfg is not None and not s["running"] and s["model"] != _target(cfg, choice)[1]:
        s.update(model=_target(cfg, choice)[1], status="", completed=0, total=0, error="", done=False)
    s["percent"] = round(100 * s["completed"] / s["total"], 1) if s["total"] else 0.0
    return s


def start(cfg, choice: str | None = None) -> dict:
    """Begin the download in the background (or report the one that is running). `choice` must be a model from the
    curated list; anything else is refused before a request is made."""
    from .localmodels import NAMES

    if choice and choice not in NAMES:
        return {**status(cfg), "running": False, "done": False, "error": "that model is not in Vaelon's list"}
    base, model = _target(cfg, choice)
    if not NAME_RX.match(model):
        return {**status(cfg, choice), "running": False, "done": False,
                "error": "the configured local model name is not valid"}
    with _lock:  # status() takes the same lock: never call it while holding it
        already = _state["running"]
        if not already:
            _state.update(running=True, model=model, status="starting", completed=0, total=0, error="", done=False,
                          started=time.time())
    if not already:
        try:
            threading.Thread(target=_pull, args=(base, model), daemon=True, name="vaelon-model-pull").start()
        except RuntimeError:  # could not start a thread: never leave "running" switched on
            with _lock:
                _state.update(running=False, error="could not start the download")
    return status(cfg, choice)


def _pull(base: str, model: str) -> None:
    layers: dict[str, tuple[int, int]] = {}  # digest -> (completed, total): Ollama reports each part on its own
    error, finished = "", False
    try:
        with requests.post(f"{base}/api/pull", json={"model": model, "stream": True}, stream=True,
                           timeout=(5, 300)) as r:
            if r.status_code != 200:
                try:
                    said = str(r.json().get("error", ""))[:200]
                except (ValueError, AttributeError):
                    said = ""
                error = f"Ollama answered {r.status_code}" + (f": {said}" if said else "")
            else:
                for line in r.iter_lines():
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(msg, dict):
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
    except Exception as e:  # an answer of an unexpected shape (another program on that address, a new Ollama)
        error = f"unexpected answer from Ollama ({type(e).__name__})"
    finally:  # whatever happened, the download is over: never leave "running" switched on
        with _lock:
            _state["running"] = False
            _state["done"] = finished and not error
            _state["error"] = error or ("" if finished else "the download stopped before it finished")
            if _state["done"]:
                _state["status"] = "success"
                _state["completed"] = _state["total"] = max(_state["total"], _state["completed"])
