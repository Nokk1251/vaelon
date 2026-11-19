"""Text-to-speech + the Voice Designer.

Engines (best available is used):
  piper       local neural voices (default, private)            pip install "vaelon[voice]"; vaelon voice-setup
  sapi        Windows' built-in voices (fallback, private)
  elevenlabs  studio-quality cloud voices (OPT-IN: text leaves your PC). vaelon key set ELEVENLABS_API_KEY,
              vaelon config tts_engine elevenlabs, optionally vaelon config elevenlabs_voice <voice id>

Voice Designer: every voice can be reshaped locally - pitch, speed, metal, robot, radio, echo, space - via presets
(vaelon, butler, titan, machine, radio, ghost, clean) or sliders in the app. No real person's voice is imitated.
"""
from __future__ import annotations

import io
from collections import OrderedDict
import re
import subprocess
import sys
import tempfile
import threading
import urllib.request
import wave
from pathlib import Path

from . import config

HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
EN_VOICES = {
    "alan": ("en/en_GB/alan/medium", "en_GB-alan-medium"),  # British male, calm assistant
    "ryan": ("en/en_US/ryan/medium", "en_US-ryan-medium"),  # American male
}

PRESETS = {
    "vaelon": {"pitch": 0.9, "speed": 1.0, "metal": 0.6, "robot": 0.1, "radio": 0.0, "echo": 0.1, "space": 0.2},
    "butler": {"pitch": 1.0, "speed": 0.95, "metal": 0.1, "robot": 0.0, "radio": 0.0, "echo": 0.0, "space": 0.25},
    "titan": {"pitch": 0.8, "speed": 0.92, "metal": 0.4, "robot": 0.0, "radio": 0.0, "echo": 0.15, "space": 0.35},
    "machine": {"pitch": 0.95, "speed": 1.0, "metal": 0.3, "robot": 0.6, "radio": 0.0, "echo": 0.0, "space": 0.1},
    "radio": {"pitch": 1.0, "speed": 1.05, "metal": 0.15, "robot": 0.0, "radio": 1.0, "echo": 0.0, "space": 0.0},
    "ghost": {"pitch": 0.85, "speed": 0.9, "metal": 0.2, "robot": 0.0, "radio": 0.0, "echo": 0.5, "space": 0.6},
    "clean": {"pitch": 1.0, "speed": 1.0, "metal": 0.0, "robot": 0.0, "radio": 0.0, "echo": 0.0, "space": 0.0},
}
LIMITS = {"pitch": (0.6, 1.5), "speed": (0.6, 1.6), "metal": (0.0, 1.0), "robot": (0.0, 1.0), "radio": (0.0, 1.0),
          "echo": (0.0, 1.0), "space": (0.0, 1.0)}


def normalize(v: dict | None) -> dict:
    """Preset + overrides, every value clamped to a safe range."""
    v = v or {}
    name = v.get("preset") if v.get("preset") in PRESETS else "vaelon"
    out = {"preset": name, **PRESETS[name]}
    for k, (lo, hi) in LIMITS.items():
        if k in v:
            try:
                out[k] = round(min(hi, max(lo, float(v[k]))), 3)
            except (TypeError, ValueError):
                pass
    return out


def current_voice(cfg=None) -> dict:
    cfg = cfg or config.Config.load()
    if cfg.voice:
        return normalize(cfg.voice)
    return normalize({"preset": "vaelon", "metal": cfg.voice_effect})  # older configs: one "effect" knob


def _voices() -> dict:
    return {"bg": ("bg/bg_BG/dimitar/medium", "bg_BG-dimitar-medium"),
            "en": EN_VOICES.get(config.Config.load().voice_en, EN_VOICES["alan"])}


def voice_dir() -> Path:
    return config.HOME / "voices"


def model_path(lang: str) -> Path:
    return voice_dir() / f"{_voices()[lang][1]}.onnx"


def detect_lang(text: str) -> str:
    return "bg" if re.search(r"[Ѐ-ӿ]", text) else "en"


def available() -> bool:
    """True if the server can synthesise speech (Piper models, or Windows' built-in voices)."""
    return any(_engine(l) for l in ("bg", "en"))


def download_voices(langs=("bg", "en")) -> None:
    voice_dir().mkdir(parents=True, exist_ok=True)
    for lang in langs:
        rel, stem = _voices()[lang]
        for ext in (".onnx", ".onnx.json"):
            dest = voice_dir() / f"{stem}{ext}"
            if dest.exists():
                continue
            print(f"downloading {stem}{ext} ...")
            urllib.request.urlretrieve(f"{HF}/{rel}/{stem}{ext}", dest)


# ------------------------------------------------------------------ effects (numpy, all local)
def vaelon_effect(samples, rate: int, amount: float = 0.6):
    """Metallic robotic colour: two short comb delays, a sub-octave layer, soft saturation. numpy float array in/out."""
    import numpy as np

    x = samples.astype(np.float32)
    out = x.copy()
    for ms, gain in ((8.5, 0.35), (13.2, 0.25)):
        d = int(rate * ms / 1000)
        out[d:] += gain * amount * x[:-d]
    sub = np.repeat(x[::2], 2)[: len(x)]  # crude octave-down
    k = int(rate / 300)
    sub = np.convolve(sub, np.ones(k) / k, mode="same")  # low-pass ~300 Hz
    out += 0.35 * amount * sub
    out = np.tanh(out * (1.0 + 0.8 * amount))  # soft-knee saturation
    peak = float(np.max(np.abs(out))) or 1.0
    return (out / peak * 0.9).astype(np.float32)


def design(samples, rate: int, v: dict):
    """Apply a Voice Designer profile. Pitch is changed by resampling (speed is compensated at synthesis time)."""
    import numpy as np

    x = samples.astype(np.float32)
    p = v.get("pitch", 1.0)
    if abs(p - 1.0) > 0.01 and len(x) > 2:
        x = np.interp(np.arange(0, len(x) - 1, p), np.arange(len(x)), x).astype(np.float32)
    if v.get("metal", 0) > 0:
        x = vaelon_effect(x, rate, v["metal"])
    r = v.get("robot", 0)
    if r > 0:  # ring modulation: the classic "machine" voice
        t = np.arange(len(x), dtype=np.float32) / rate
        x = x * (1 - r) + x * np.sin(2 * np.pi * 55 * t).astype(np.float32) * r * 1.6
    rad = v.get("radio", 0)
    if rad > 0:  # telephone/radio band (~300-3400 Hz) with a little grit
        k_hi, k_lo = max(1, int(rate / 3400)), max(2, int(rate / 300))
        lp = np.convolve(x, np.ones(k_hi) / k_hi, mode="same")
        band = lp - np.convolve(lp, np.ones(k_lo) / k_lo, mode="same")
        x = x * (1 - rad) + np.tanh(band * 3.0) * rad
    sp = v.get("space", 0)
    if sp > 0:  # small room: a few early reflections
        y = np.concatenate([x, np.zeros(int(rate * 0.08), np.float32)])
        for ms, g in ((23, 0.5), (37, 0.4), (53, 0.32), (71, 0.25)):
            d = int(rate * ms / 1000)
            y[d:d + len(x)] += x * g * sp * 0.6
        x = y
    e = v.get("echo", 0)
    if e > 0:  # three fading repeats
        d = int(rate * 0.21)
        y = np.concatenate([x, np.zeros(d * 3, np.float32)])
        for k in (1, 2, 3):
            y[d * k:d * k + len(x)] += x * (0.45 * e) ** k
        x = y
    peak = float(np.max(np.abs(x))) or 1.0
    return (x / peak * 0.9).astype(np.float32)


def _read_wav(wav_bytes: bytes):
    import numpy as np

    with wave.open(io.BytesIO(wav_bytes)) as w:
        rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        return None, rate
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, rate


def _write_wav(x, rate: int) -> bytes:
    import numpy as np

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


def apply_effect_wav(wav_bytes: bytes, amount: float = 0.6) -> bytes:
    x, rate = _read_wav(wav_bytes)
    return wav_bytes if x is None else _write_wav(vaelon_effect(x, rate, amount), rate)


def apply_design_wav(wav_bytes: bytes, v: dict) -> bytes:
    x, rate = _read_wav(wav_bytes)
    return wav_bytes if x is None else _write_wav(design(x, rate, v), rate)


# ------------------------------------------------------------------ engines
SAPI_PS1 = r"""param($TextFile, $OutFile, $Lang)
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -like "$Lang*" } | Select-Object -First 1
if (-not $v) { exit 3 }
$s.SelectVoice($v.VoiceInfo.Name)
$s.Rate = -1
$s.SetOutputToWaveFile($OutFile)
$s.Speak([IO.File]::ReadAllText($TextFile, [Text.Encoding]::UTF8))
$s.Dispose()
"""


def _piper_ready(lang: str) -> bool:
    try:
        import piper  # noqa: F401
    except ImportError:
        return False
    return model_path(lang).exists()


def _engine(lang: str) -> str | None:
    """elevenlabs (only if chosen AND keyed) -> piper (neural, local) -> sapi (Windows) -> None."""
    cfg = config.Config.load()
    if cfg.tts_engine == "elevenlabs" and config.env("ELEVENLABS_API_KEY"):
        return "elevenlabs"
    if cfg.tts_engine in ("auto", "piper", "elevenlabs") and _piper_ready(lang):
        return "piper"
    if sys.platform in ("win32", "darwin"):
        return "sapi"  # the system's own voice: Windows SAPI, or `say` on a Mac
    return None


_voice_cache: dict = {}
_voice_locks: dict = {}
_voice_guard = threading.Lock()


def _voice_lock(lang: str) -> threading.Lock:
    """One lock per voice: the two languages load and speak side by side, one voice never overlaps itself."""
    with _voice_guard:
        return _voice_locks.setdefault(lang, threading.Lock())


def _piper(text: str, lang: str, length_scale: float = 1.0) -> bytes:
    """In-process Piper: the model is loaded once and kept in memory."""
    from piper import PiperVoice

    with _voice_lock(lang):
        voice = _voice_cache.get(lang)
        if voice is None:
            voice = _voice_cache[lang] = PiperVoice.load(str(model_path(lang)))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            if hasattr(voice, "synthesize_wav"):
                syn = None
                if abs(length_scale - 1.0) > 0.01:
                    from piper.config import SynthesisConfig

                    syn = SynthesisConfig(length_scale=length_scale)
                voice.synthesize_wav(text, w, syn_config=syn)
            else:  # piper-tts < 1.3
                voice.synthesize(text, w)
        return buf.getvalue()


def _sapi(text: str, lang: str, td: Path) -> bytes:
    if sys.platform == "darwin":  # the Mac's own voice (`say`), text from a file
        from . import platform_mac

        return platform_mac.say(text, lang)
    script, txt, out = td / "speak.ps1", td / "t.txt", td / "o.wav"
    script.write_text(SAPI_PS1, "utf-8-sig")
    txt.write_text(text, "utf-8")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                        str(txt), str(out), lang], capture_output=True, timeout=60)
    if r.returncode == 3:
        raise RuntimeError(f"no installed Windows voice for '{lang}' - add one in Settings > Time & language > "
                           f"Speech, or run: vaelon voice-setup (Piper)")
    if r.returncode != 0 or not out.exists():
        raise RuntimeError("Windows speech synthesis failed: " + r.stderr.decode("utf-8", "replace")[:200])
    return out.read_bytes()


def _usage_path():
    return config.HOME / "usage.json"


_usage_lock = threading.Lock()  # sentences are voiced in parallel: check-and-count is one step
_cache_lock = threading.RLock()


def elevenlabs_used() -> int:
    import json
    import time

    p = _usage_path()
    if not p.exists():
        return 0
    try:
        u = json.loads(p.read_text("utf-8"))
    except Exception:
        return 10**9  # unreadable: treat the month's cap as reached (never as "nothing used yet")
    return int(u.get("elevenlabs_chars", 0)) if u.get("month") == time.strftime("%Y-%m") else 0


def _add_usage(chars: int) -> None:
    """Count characters (negative = give back a reservation the cloud never used). Written atomically."""
    import json
    import os
    import time

    with _usage_lock:
        used = elevenlabs_used()
        if used >= 10**9:
            return
        tmp = _usage_path().with_suffix(".tmp")
        tmp.write_text(json.dumps({"month": time.strftime("%Y-%m"), "elevenlabs_chars": max(0, used + chars)}), "utf-8")
        os.replace(tmp, _usage_path())


def reserve(text: str) -> bool:
    """Claim the characters BEFORE the cloud request (parallel sentences cannot all slip under the cap together)."""
    import json
    import os
    import time

    with _usage_lock:
        used = elevenlabs_used()
        if used + len(text) > max(0, config.Config.load().elevenlabs_monthly_chars):
            return False
        tmp = _usage_path().with_suffix(".tmp")
        tmp.write_text(json.dumps({"month": time.strftime("%Y-%m"), "elevenlabs_chars": used + len(text)}), "utf-8")
        os.replace(tmp, _usage_path())
        return True


def _budget_ok(text: str) -> bool:
    return elevenlabs_used() + len(text) <= max(0, config.Config.load().elevenlabs_monthly_chars)


ELEVEN = "https://api.elevenlabs.io"  # spoken through the shared keep-alive pool (speed.HTTP): no new handshake per sentence


def _elevenlabs(text: str) -> bytes:
    """Cloud voice (opt-in). Raw 16-bit PCM is requested so the Voice Designer can still shape it locally."""
    from . import speed

    cfg = config.Config.load()
    vid = re.sub(r"[^A-Za-z0-9]", "", cfg.elevenlabs_voice or "JBFqnCBsd6RMkjVDRZzb")
    from .security.dlp import scrub

    model = re.sub(r"[^a-z0-9_]", "", cfg.elevenlabs_model or "eleven_flash_v2_5")
    speed.used(ELEVEN)
    r = speed.HTTP.post(f"{ELEVEN}/v1/text-to-speech/{vid}", params={"output_format": "pcm_22050"},
                      headers={"xi-api-key": config.env("ELEVENLABS_API_KEY")}, timeout=60,
                      allow_redirects=False,  # the key header must never follow a redirect to another host
                      json={"text": scrub(text), "model_id": model})
    r.raise_for_status()  # counted already (reserve) - a failure here gives the characters back in _synthesize
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(r.content)
    return buf.getvalue()


_wav_cache: "OrderedDict[tuple, bytes]" = OrderedDict()


def synthesize(text: str, effect: float | None = None, voice: dict | None = None) -> bytes:
    """Return WAV bytes for `text` (language auto-detected), shaped by the Voice Designer profile `voice`
    (default: the saved one). Recently spoken sentences come from a small cache."""
    text = text.strip()[:1500]
    if not text:
        raise ValueError("empty text")
    v = normalize(voice) if voice else current_voice()
    if effect is not None and not voice:
        v["metal"] = max(0.0, min(1.0, float(effect)))
    key = cache_key(text, v)
    hit = cached(key)
    if hit is not None:
        return hit
    return remember(key, _synthesize(text, v))


def cached(key: tuple) -> bytes | None:
    with _cache_lock:  # the clip cache is shared by parallel /tts requests
        wav = _wav_cache.get(key)
        if wav is not None:
            _wav_cache.move_to_end(key)
        return wav


def cache_key(text: str, v: dict) -> tuple:
    return (text, tuple(sorted((k, val) for k, val in v.items() if k != "preset")))


def remember(key: tuple, wav: bytes) -> bytes:
    """Keep a finished clip: the same sentence is not synthesised (or paid for) twice in a row."""
    with _cache_lock:
        _wav_cache[key] = wav
        _wav_cache.move_to_end(key)
        while len(_wav_cache) > 64:
            _wav_cache.popitem(last=False)
    return wav


def _synthesize(text: str, v: dict, local_only: bool = False) -> bytes:
    lang = detect_lang(text)
    engine = _engine(lang)
    if engine is None:
        raise FileNotFoundError(f"no voice for '{lang}' on this computer - add a system voice (Help > Voice)")
    wav = None
    if engine == "elevenlabs" and (local_only or not reserve(text)):  # cap reached / cloud just failed: local voice
        engine = "piper" if _piper_ready(lang) else ("sapi" if sys.platform in ("win32", "darwin") else None)
        if engine is None:
            raise RuntimeError("ElevenLabs monthly cap reached and no local voice for this language (Help > Voice)")
    if engine == "elevenlabs":
        try:
            wav = _elevenlabs(text)
        except Exception:
            _add_usage(-len(text))  # refused / unreachable: not billed
            engine = "piper" if _piper_ready(lang) else ("sapi" if sys.platform in ("win32", "darwin") else None)
            if engine is None:
                raise
    if wav is None:
        with tempfile.TemporaryDirectory() as td:
            if engine == "piper":
                # pitch is changed later by resampling, which also speeds up: stretch here to compensate
                wav = _piper(text, lang, length_scale=v["pitch"] / max(v["speed"], 0.1))
            else:
                wav = _sapi(text, lang, Path(td))
    if all(v[k] == 0 for k in ("metal", "robot", "radio", "echo", "space")) and abs(v["pitch"] - 1) <= 0.01:
        return wav
    try:
        return apply_design_wav(wav, v)
    except ImportError:  # numpy missing: plain voice is better than no voice
        return wav


def engines_status() -> dict:
    """What the Voice panel shows: which engines exist and which one speaks right now."""
    cfg = config.Config.load()
    return {"selected": cfg.tts_engine, "speaking": _engine("bg") or _engine("en"),
            "piper": _piper_ready("bg") or _piper_ready("en"), "windows": sys.platform in ("win32", "darwin"),
            "elevenlabs": bool(config.env("ELEVENLABS_API_KEY")),
            "elevenlabs_used": elevenlabs_used(), "elevenlabs_cap": cfg.elevenlabs_monthly_chars}


WARM_WORDS = {"en": "Ready.", "bg": "Готово."}
READY: dict = {}  # lang -> seconds the warm-up took (for `vaelon doctor` and the tests)


UI_UP = threading.Event()  # set when the app's window has asked for its page (see server._static)


def warmup(wait: float = 0.0) -> None:
    """Load the local voices in the background - both at once - and let each say one word to itself: loading alone
    leaves the first real sentence about half a second slower (the model's first run is its slowest).
    `wait`: hold back until the window has asked for its page (or that many seconds at most). Loading two voice
    models while the app is still starting made the window appear a full second later (measured)."""
    def work(lang: str):
        import time

        if wait > 0:
            UI_UP.wait(wait)
        t = time.perf_counter()
        try:
            if _engine(lang) == "piper":
                _piper(WARM_WORDS[lang], lang)
                READY[lang] = round(time.perf_counter() - t, 2)
        except Exception:
            pass

    for lang in WARM_WORDS:
        threading.Thread(target=work, args=(lang,), daemon=True, name=f"vaelon-voice-{lang}").start()

    def cloud():
        # the streamed cloud voice needs numpy: loading it costs ~0.3 s, paid here instead of on the first sentence
        # (only when ElevenLabs is the chosen voice - otherwise it would take memory for nothing)
        if wait > 0:
            UI_UP.wait(wait)
        try:
            if config.Config.load().tts_engine == "elevenlabs" and config.env("ELEVENLABS_API_KEY"):
                from . import voicestream  # noqa: F401
        except Exception:
            pass

    threading.Thread(target=cloud, daemon=True, name="vaelon-voice-cloud").start()
