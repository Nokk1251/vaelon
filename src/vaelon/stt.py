"""Speech-to-text for the app's microphone button.

Engines (stt_engine = auto | local | groq):
  groq    Whisper large-v3-turbo on Groq: accurate in Bulgarian and English, ~1 s. "auto" uses it ONLY when Groq is
          already your model provider (your words go there anyway as text) - no NEW service receives your data.
  local   faster-whisper on this PC: fully private, weaker in Bulgarian with small models, not bundled in the .exe
          (pip install "vaelon[voice]"). Force it with:  vaelon config stt_engine local
Audio is never written to disk and never kept.
"""
from __future__ import annotations

import io
import re

from . import config

MAX_BYTES = 8 * 1024 * 1024  # ~4 minutes of compressed speech
NAME_HINT = "Vaelon"  # tells Whisper the unusual word it will hear; without it "Vaelon" comes out as "Valon"
# what speech recognition makes of the name: the user means Vaelon (Bulgarian: Вейлон)
NAME_FIXES = (
    (re.compile(r"\b(?:Valon|Vallon|Vaylon|Vailon|Vaelin|Vaylan|Vailin|Velon|Vayelon|Vaelon|Waelon|Welon|Walon|"
                r"Vealon|Vaeylon|Vaellon|Vaylen|Vaelen|Vaelan)\b", re.I), "Vaelon"),  # never Waylon: a real name
    (re.compile(r"(?<![А-Яа-яЁё])(?:Валон|Вайлон|Вейлън|Велон|Вейлон|Ваелон|Уейлон|Уелон|Вейлан|Веалон)(?=[^А-Яа-яЁё]|$)", re.I), "Вейлон"),
)


def fix_name(text: str) -> str:
    for rx, right in NAME_FIXES:
        text = rx.sub(right, text)
    return text
GROQ_STT = "https://api.groq.com/openai/v1/audio/transcriptions"


def _local_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _groq_allowed(cfg) -> bool:
    return "groq.com" in (cfg.base_url or "") and bool(config.env("GROQ_API_KEY"))


def engine(cfg=None) -> str | None:
    cfg = cfg or config.Config.load()
    if cfg.stt_engine == "local":
        return "local" if _local_available() else None
    if cfg.stt_engine in ("auto", "groq") and _groq_allowed(cfg):
        return "groq"
    if cfg.stt_engine == "auto" and _local_available():
        return "local"
    return None


_model = None
_model_lock = __import__("threading").Lock()  # the window and the companion may ask at once: load Whisper ONCE


def _local(audio: bytes, cfg) -> str:
    global _model
    from faster_whisper import WhisperModel

    with _model_lock:
        if _model is None:
            _model = WhisperModel(cfg.whisper_model or "base", device="cpu", compute_type="int8")
    pcm = _wav_to_16k(audio)  # WAV is decoded here - no PyAV/ffmpeg needed
    segments, _ = _model.transcribe(pcm if pcm is not None else io.BytesIO(audio), vad_filter=True,
                                    initial_prompt=NAME_HINT)
    return " ".join(s.text.strip() for s in segments).strip()


def _wav_to_16k(audio: bytes):
    """16-bit PCM WAV -> float32 mono 16 kHz numpy array (what Whisper wants), or None if it is not WAV."""
    if audio[:4] != b"RIFF":
        return None
    import wave

    import numpy as np

    with wave.open(io.BytesIO(audio)) as w:
        rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        return None
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if rate != 16000 and len(x) > 1:
        x = np.interp(np.arange(0, len(x), rate / 16000), np.arange(len(x)), x).astype(np.float32)
    return x


def _groq(audio: bytes, mime: str) -> str:
    from . import speed  # the shared keep-alive pool: the model call right after this reuses the same connection

    speed.used(GROQ_STT)
    ext = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/wav": "wav", "audio/x-wav": "wav",
           "audio/mp4": "m4a", "audio/mpeg": "mp3"}.get(mime.split(";")[0].strip(), "webm")
    r = speed.HTTP.post(GROQ_STT, headers={"Authorization": f"Bearer {config.env('GROQ_API_KEY')}"},
                      files={"file": (f"speech.{ext}", audio, mime.split(";")[0] or "audio/webm")},
                      data={"model": "whisper-large-v3-turbo", "response_format": "json", "temperature": "0",
                            "prompt": NAME_HINT},
                      timeout=60, allow_redirects=False)
    r.raise_for_status()
    return (r.json().get("text") or "").strip()


def transcribe(audio: bytes, mime: str = "audio/webm") -> str:
    if not audio:
        raise ValueError("no audio")
    if len(audio) > MAX_BYTES:
        raise ValueError("recording too long")
    cfg = config.Config.load()
    return fix_name(_transcribe(audio, mime, cfg))


def _transcribe(audio: bytes, mime: str, cfg) -> str:
    eng = engine(cfg)
    if eng == "local":
        try:
            return _local(audio, cfg)
        except Exception:
            if not (cfg.stt_engine == "auto" and _groq_allowed(cfg)):
                raise
            eng = "groq"  # local engine broken or missing a model: the cloud you already use takes over
    if eng == "groq":
        return _groq(audio, mime)
    raise RuntimeError("no speech-to-text engine: pip install \"vaelon[voice]\" (local) or use Groq "
                       "(vaelon provider groq + vaelon key set)")
