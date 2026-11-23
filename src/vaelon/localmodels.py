"""Which local model to use: a short, curated list and a look at this computer, so a person who has never heard of
"quantisation" can still pick well.

- CATALOG: a few models from Ollama's library, each for a kind of computer. Download sizes were read from Ollama's
  registry (registry.ollama.ai manifests, 2026-11-23); what each model is good for follows Ollama's own model pages.
  Models that think out loud (e.g. qwen3:4b, qwen3:8b) are left out on purpose: their reasoning leaks into answers.
- machine(): memory (total / free), processor, graphics - read on this computer, never sent anywhere.
- assess(): for every model, whether it fits this computer and roughly how fast it will feel. Memory need is an
  ESTIMATE (the model's size + 1.5 GB for the working space); the app says so.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import threading

OVERHEAD_GB = 1.5  # working space next to the model (context, runtime): an estimate, said as such in the app

CATALOG = [
    {"name": "llama3.2:3b", "size_gb": 2.02, "vision": False,
     "good_for": "The lightest: quick everyday answers on a modest computer. Best in English."},
    {"name": "qwen3:4b-instruct", "size_gb": 2.50, "vision": False,
     "good_for": "Balanced and Vaelon's default: good with its tools, documents and many languages."},
    {"name": "gemma3:4b", "size_gb": 3.35, "vision": True,
     "good_for": "Also understands pictures; over 140 languages."},
    {"name": "qwen2.5:7b", "size_gb": 4.68, "vision": False,
     "good_for": "Smarter, longer answers in many languages - for a stronger computer."},
    {"name": "gemma3:12b", "size_gb": 8.16, "vision": True,
     "good_for": "The most capable here, also with pictures - for 16 GB of memory or more."},
]
NAMES = {m["name"] for m in CATALOG}

_cache: dict = {"machine": None}
_lock = threading.Lock()
# PowerShell writes its pipe in the console code page unless told otherwise; this makes it UTF-8
_UTF8 = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "


def _powershell() -> str:
    """The system PowerShell by its full path (a bare name would also be looked for in the current folder)."""
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    full = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return full if os.path.exists(full) else "powershell"


def _memory() -> tuple[float, float]:
    """(total GB, free GB)."""
    try:
        import psutil

        m = psutil.virtual_memory()
        return m.total / 1e9, m.available / 1e9
    except Exception:
        pass
    if sys.platform == "win32":
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                        ("avail", ctypes.c_ulonglong), ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong),
                        ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ae", ctypes.c_ulonglong)]

        s = MS()
        s.len = ctypes.sizeof(MS)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)):
            return s.total / 1e9, s.avail / 1e9
    return 0.0, 0.0


def _run(args: list[str], timeout: float = 8) -> str:
    """A fixed system command (argument list, no shell), its text output or ''."""
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, creationflags=flags)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""


def _graphics() -> list[dict]:
    """[{name, vram_gb, kind}] - kind: 'nvidia', 'amd', 'apple', 'integrated' or 'other'. Best effort, never fails."""
    try:
        return _read_graphics()
    except Exception:
        return []


def _read_graphics() -> list[dict]:
    out = []
    if sys.platform == "darwin" and platform.machine() == "arm64":
        return [{"name": "Apple silicon (shares the computer's memory)", "vram_gb": 0.0, "kind": "apple"}]
    smi = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
    for line in smi.splitlines():
        name, _, mib = line.partition(",")
        try:
            out.append({"name": name.strip(), "vram_gb": round(float(mib) / 1024, 1), "kind": "nvidia"})
        except ValueError:
            pass
    if sys.platform == "win32":
        raw = _run([_powershell(), "-NoProfile", "-NonInteractive", "-Command",
                    _UTF8 + "Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM | ConvertTo-Json -Compress"])
        try:
            rows = json.loads(raw) if raw.strip() else []
        except ValueError:
            rows = []
        for row in rows if isinstance(rows, list) else [rows]:
            name = str((row or {}).get("Name") or "").strip()
            if not name or any(g["name"] == name for g in out):
                continue
            low = name.lower()
            kind = "nvidia" if "nvidia" in low else "amd" if ("amd" in low or "radeon" in low) else "other"
            # AdapterRAM is a 32-bit number (at most 4 GB) and tiny for graphics built into the processor
            try:
                vram = float(row.get("AdapterRAM") or 0) / 1e9
            except (TypeError, ValueError):
                vram = 0.0
            # graphics built into a Ryzen processor: "AMD Radeon(TM) Graphics", "AMD Radeon 780M Graphics" (no RX / Pro)
            words = low.replace("(tm)", " ").split()
            if kind == "amd" and (vram < 1.5 or ("graphics" in words and not {"rx", "pro"} & set(words))):
                kind = "integrated"
            if "intel" in low and ("uhd" in low or "iris" in low or "hd graphics" in low):
                kind = "integrated"
            out.append({"name": name, "vram_gb": round(vram, 1), "kind": kind})
    return out


def _processor() -> str:
    name = ""
    if sys.platform == "win32":
        name = _run([_powershell(), "-NoProfile", "-NonInteractive", "-Command",
                     _UTF8 + "(Get-CimInstance Win32_Processor | Select-Object -First 1).Name"]).strip()
    elif sys.platform == "darwin":
        name = _run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
    return (name or platform.processor() or platform.machine())[:80]


def machine(refresh: bool = False) -> dict:
    """What this computer has. Processor and graphics are read once (they do not change while Vaelon runs); free
    memory is read fresh every time."""
    total, free = _memory()
    with _lock:
        if refresh or not _cache["machine"]:
            _cache["machine"] = {"processor": _processor(), "cores": os.cpu_count() or 0, "graphics": _graphics(),
                                 "apple_silicon": sys.platform == "darwin" and platform.machine() == "arm64"}
    return {**_cache["machine"], "memory_gb": round(total, 1), "free_gb": round(free, 1)}


def _accel_gb(m: dict) -> float:
    """Memory a fast graphics chip can give a model (0 = the processor does the work)."""
    if m.get("apple_silicon"):
        return m.get("memory_gb", 0) * 0.65  # unified memory: macOS lets the graphics part use about two thirds
    return max([g["vram_gb"] for g in m.get("graphics", []) if g["kind"] in ("nvidia", "amd")] or [0.0])


def assess(m: dict, installed: list[str], in_use: str) -> list[dict]:
    """The catalog with, for each model: memory need, whether it fits, how fast it will feel, recommended or not."""
    have = {n.removesuffix(":latest") for n in installed}
    accel = _accel_gb(m)
    rows = []
    for c in CATALOG:
        need = round(c["size_gb"] + OVERHEAD_GB, 1)
        # the model in use is usually loaded already: its memory counts as "taken", but it is its own
        free = m["free_gb"] + (c["size_gb"] if c["name"] == in_use and c["name"] in have else 0)
        if m["memory_gb"] and need > m["memory_gb"]:
            fit = "too_big"
        elif m["free_gb"] and need > free:
            fit = "tight"  # fits the computer, but other programs would have to give memory back first
        else:
            fit = "ok"
        if accel >= need:
            speed = "fast"
        elif c["size_gb"] <= 2.6:
            speed = "usable"
        elif c["size_gb"] <= 5:
            speed = "slow"
        else:
            speed = "very_slow"
        if speed != "fast" and 0 < (m.get("cores") or 0) < 4:  # a small processor does the work: one step slower
            speed = {"usable": "slow", "slow": "very_slow"}.get(speed, speed)
        rows.append({**c, "need_gb": need, "fit": fit, "speed": speed, "installed": c["name"] in have,
                     "in_use": c["name"] == in_use, "recommended": False})
    rec = _recommend(m, accel)
    for r in rows:
        r["recommended"] = r["name"] == rec and r["fit"] != "too_big"  # never recommend what cannot run here
    return rows


def _recommend(m: dict, accel: float) -> str:
    """One sensible choice for this computer - a starting point, never a rule."""
    total = m.get("memory_gb") or 0
    if total and total < 8:
        return "llama3.2:3b"
    if accel >= 9.7 and total >= 16:
        return "gemma3:12b"
    if accel >= 6.2:
        return "qwen2.5:7b"
    return "qwen3:4b-instruct"
