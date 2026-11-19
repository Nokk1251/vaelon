"""Secret leak prevention (DLP) - the last line of defence for your API keys.

Pattern-based redaction (redact.py) catches known key formats. This module catches the EXACT values of the keys
you stored, whatever their format:
- `find(text)`   -> which secret appears in a tool call / URL / message  (the call is then blocked)
- `scrub(text)`  -> replaces stored secret values with [REDACTED:NAME]   (logs, memory, model input, tool output)
- `safe_env()`   -> a copy of the environment WITHOUT secrets, for every program Vaelon starts
- `SECRET_ACCESS` -> commands that try to reach the vault or Windows DPAPI are refused outright
Values are read from the vault/env once a minute and kept only in this process's memory.
"""
from __future__ import annotations

import os
import re
import threading
import time

from .. import config

MIN_LEN = 12  # shorter values are not treated as secrets (too many false matches)
TTL = 60.0
SECRET_NAME = re.compile(r"(?i)(API_?KEY|TOKEN|SECRET|PASSWORD|_PASS$|AUTH|ACCOUNT_SID)")
SECRET_ACCESS = re.compile(
    r"(?i)\.(vaelon|" + config.LEGACY_NAME + r")[\\/]+secrets|[\\/]secrets[\\/]+(key_|master\.key|api_token)|ProtectedData|CryptUnprotect|find-generic-password|find-internet-password|dump-keychain|security\s+export|keychain-db|vault-wrap-key|generic-password\b[^\n]*\bVaelon\b"
    r"|Unprotect-?CmsMessage|dpapi|mimikatz|\bkey_[A-Z0-9_]{4,}\b")

_lock = threading.Lock()
_cache: dict = {"t": 0.0, "vals": {}}


def known_names() -> set[str]:
    names = set()
    try:
        from ..providers import EXTRA_KEYS, PRESETS

        names |= {p["api_key_env"] for p in PRESETS.values() if p["api_key_env"]} | set(EXTRA_KEYS)
    except Exception:
        pass
    names |= {"VAELON_API_KEY", "TWILIO_FROM", "VAELON_SMTP_USER", "VAELON_IMAP_PASS"}
    d = config.HOME / "secrets"
    if d.is_dir():
        names |= {f.name[4:] for f in d.glob("key_*")}
    return names


def secret_values() -> dict[str, str]:
    """{value: NAME} for every stored or exported secret (cached for a minute)."""
    with _lock:
        if time.time() - _cache["t"] < TTL:
            return _cache["vals"]
    vals: dict[str, str] = {}
    for name in known_names():
        if name in ("TWILIO_FROM", "VAELON_SMTP_USER"):
            continue  # phone number / email address: identifiers, not secrets
        try:
            v = config.env(name)
        except Exception:
            v = ""
        if v and len(v) >= MIN_LEN:
            vals[v] = name
    try:
        from . import vault

        tok = vault.read_secret("api_token")
        if tok and len(tok) >= MIN_LEN:
            vals[tok.decode()] = "VAELON_ACCESS_KEY"
    except Exception:
        pass
    with _lock:
        _cache.update(t=time.time(), vals=vals)
    return vals


def forget_cache() -> None:
    with _lock:
        _cache.update(t=0.0, vals={})


def find(text: str) -> str | None:
    if not text:
        return None
    for value, name in secret_values().items():
        if value in text:
            return name
    return None


def scrub(text: str) -> str:
    if not text:
        return text
    for value, name in secret_values().items():
        if value in text:
            text = text.replace(value, f"[REDACTED:{name}]")
    return text


KEY_SHAPES = re.compile(r"(?i)^(gsk_|sk[-_]|sk-ant-|sk-or-|csk-|AIza|xox[abprs]-|gh[pousr]_|AKIA)")


def looks_like_secret(text: str) -> bool:
    """True if `text` looks like an API key rather than a key NAME (catches a key pasted in the wrong place)."""
    t = (text or "").strip()
    if KEY_SHAPES.match(t):
        return True
    return len(t) >= 32 and bool(re.search(r"\d", t)) and bool(re.search(r"[a-z]", t)) and "_" not in t[:3]


def safe_env() -> dict[str, str]:
    """Environment for child processes: no API keys, tokens or passwords are inherited."""
    names = known_names()
    return {k: v for k, v in os.environ.items() if k not in names and not SECRET_NAME.search(k)}
