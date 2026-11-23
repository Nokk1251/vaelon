"""Configuration. Secrets are NEVER stored here - only read from environment variables."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

LEGACY_NAME = "ultron"  # working title of the private builds made before the first public release


def _home() -> Path:
    """Where Vaelon keeps its data (VAELON_HOME overrides). Data written by a private pre-release build lives in the
    old folder: it is moved here once, as it is - nothing inside is changed or re-encrypted, so keys, memory and
    history keep working. If the old folder is in use right now, Vaelon keeps working there and tries again later."""
    explicit = os.environ.get("VAELON_HOME") or os.environ.get(LEGACY_NAME.upper() + "_HOME")
    if explicit:
        return Path(explicit)
    new, old = Path.home() / ".vaelon", Path.home() / ("." + LEGACY_NAME)
    if not new.exists() and old.is_dir():
        try:
            old.rename(new)
        except OSError:
            return old
    return new


HOME = _home()


# Settings that decide where your text goes and what may run without asking. config.json is a plain file: anything
# that can write it could send every prompt to its own server (base_url) or open all folders. Vaelon keeps a SEALED copy
# of these (vault) - written only by Vaelon's own save. A value changed in the file by something else is not used:
# the last trusted value is, and the owner is told (Settings banner; `vaelon config confirm` accepts the file).
GUARDED = ("provider", "base_url", "api_key_env", "allowed_roots", "auto_approve", "output_dir", "api_port", "fallbacks",
           "telegram_allowed_chats")
ALERTS: list[str] = []  # guarded fields that were changed outside Vaelon (shown to the owner)


def _guard_read() -> dict | None:
    try:
        from .security import vault

        raw = vault.read_secret("config_guard")
        return json.loads(raw) if raw else None
    except Exception:
        return None


def guard_seal(data: dict) -> None:
    """Remember the security settings as Vaelon itself wrote them (or as the owner confirmed them)."""
    try:
        from .security import vault

        vault.write_secret("config_guard", json.dumps({k: data.get(k) for k in GUARDED}, sort_keys=True).encode())
    except Exception:
        pass


@dataclass
class Config:
    provider: str = "ollama"  # ollama | openai | anthropic | mock
    model: str = "qwen3:4b-instruct"  # = providers.PRESETS["local"]["model"] (what the setup offers to download)
    base_url: str = ""
    address_as: str = "Boss"
    language: str = "auto"  # reply in the user's language
    allowed_roots: list = field(default_factory=lambda: [str(Path.home())])
    redact_outbound: bool = True  # scrub secrets before text leaves the machine
    auto_approve: list = field(default_factory=list)  # tools that skip confirmation (never when tainted)
    telegram_allowed_chats: list = field(default_factory=list)
    wake_word: str = "vaelon"
    whisper_model: str = "small"
    max_steps: int = 12
    smtp_host: str = ""
    smtp_port: int = 587
    imap_host: str = ""
    fallbacks: list = field(default_factory=list)  # e.g. [{"provider":"ollama","model":"llama3.2"}]
    max_context_chars: int = 60000
    num_ctx: int = 4096  # model context window; smaller = less RAM, faster on weak PCs
    max_tokens: int = 400  # hard cap on answer length (stops rambling, saves time)
    voice_en: str = "alan"  # English voice: alan (British, Jarvis-like) | ryan (American)
    auto_learn: bool = True  # after multi-step tasks, save reusable skills and lessons (never on tainted turns)
    study_topics: list = field(default_factory=lambda: [
        "fast local llm agent tool calling", "python windows desktop automation", "prompt injection defense"])
    vision_model: str = "gemma3:4b"  # local Ollama model used to see the screen / images
    voice_effect: float = 0.6  # 0 = clean voice, 1 = very metallic Vaelon
    api_port: int = 8765  # local API for the Orb UI / phone bridge (127.0.0.1 only)
    voice: dict = field(default_factory=dict)  # Voice Designer profile: {"preset": "vaelon", "pitch": 0.9, ...}
    tts_engine: str = "auto"  # auto (piper -> windows) | piper | sapi | elevenlabs (cloud, opt-in)
    elevenlabs_voice: str = ""  # ElevenLabs voice id (your own designed voice); empty = a stock voice
    elevenlabs_model: str = "eleven_flash_v2_5"  # cheaper (0.5-1 credit/char) and faster than eleven_multilingual_v2
    stt_engine: str = "auto"  # microphone: auto (local whisper, else Groq if it is your provider) | local | groq
    elevenlabs_monthly_chars: int = 8000  # Vaelon's own cap per calendar month; then it switches to the local voice
    api_key_env: str = ""  # name of the key for the cloud model, e.g. GROQ_API_KEY (stored with `vaelon key set`)
    live_model: str = "gemini-3.1-flash-live-preview"  # Gemini Live model for real-time voice (opt-in)
    live_voice: str = "Charon"  # one of Google's built-in Live voices
    vision_cloud_model: str = ""  # cloud model that looks at pictures; empty = the known one for your provider
    output_dir: str = ""  # where created files go; empty = ~/Documents/Vaelon
    update_check: bool = False  # ask GitHub once a day whether a newer Vaelon exists (off until the user turns it on)
    setup_done: bool = False  # the first-run setup in the app was finished (or skipped)
    profiles: list = field(default_factory=list)  # optional focus: business, learning, coding, creator, life (focus.py)

    @property
    def is_local(self) -> bool:
        if self.provider in ("ollama", "mock") and not self.base_url:
            return True
        from urllib.parse import urlparse

        try:
            host = (urlparse(self.base_url or "").hostname or "").lower()
        except ValueError:
            return False
        return host in ("localhost", "127.0.0.1", "::1")  # "https://localhost.evil.com" is NOT local

    @staticmethod
    def path() -> Path:
        return HOME / "config.json"

    @classmethod
    def load(cls) -> "Config":
        p = cls.path()
        data = {}
        if p.exists():
            try:
                data = json.loads(p.read_text("utf-8"))
            except Exception:
                data = {}
        names = {f.name for f in fields(cls)}
        if data and "setup_done" not in data:
            data["setup_done"] = True  # settings from before the first-run setup existed: already set up
        if data.get("wake_word") == LEGACY_NAME:  # settings saved by a pre-release build
            data["wake_word"] = "vaelon"
        if isinstance(data.get("voice"), dict) and data["voice"].get("preset") == LEGACY_NAME:
            data["voice"] = {**data["voice"], "preset": "vaelon"}
        if p.exists():
            sealed = _guard_read()
            if sealed is None:
                guard_seal(data)  # first time: what is there now is the baseline
            else:
                changed = [k for k in GUARDED if data.get(k) != sealed.get(k)]
                for k in changed:
                    if sealed.get(k) is None:
                        data.pop(k, None)  # back to the default
                    else:
                        data[k] = sealed[k]
                ALERTS[:] = changed
        for f in fields(cls):  # an on/off setting is true/false (or 1/0); anything else ("no", "false") -> its default
            v = data.get(f.name)
            if f.type in ("bool", bool) and f.name in data and not isinstance(v, bool):
                data[f.name] = bool(v) if type(v) is int and v in (0, 1) else f.default
        return cls(**{k: v for k, v in data.items() if k in names})

    def save(self) -> None:
        HOME.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        self.path().write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
        guard_seal(data)  # Vaelon's own change: the new trusted values


def env(name: str) -> str:
    """A secret: environment variable first, then the encrypted vault (`vaelon key set NAME`). Never config.json."""
    val = os.environ.get(name, "")
    if val or not name:
        return val
    try:
        from .security import vault

        sealed = vault.read_secret("key_" + name)
        if sealed:
            return sealed.decode()
    except Exception:
        return ""
    if name.startswith("VAELON_"):  # a key stored under its pre-release name still works
        return env(LEGACY_NAME.upper() + name[len("VAELON"):])
    return ""
