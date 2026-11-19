"""macOS: the parts Windows does differently, in one place.

- The vault's master key is wrapped with a key kept in the macOS **Keychain** (the system's protected store, like DPAPI
  on Windows): a copy of ~/.vaelon alone cannot be decrypted. Uses the `keyring` package (macOS Security framework).
- Notifications through Notification Center (`osascript`), with the words passed as ARGUMENTS, never as script text.
- A local voice when Piper has none for a language: the built-in `say` command, text from a file.
- Opening a document / showing it in Finder: `open` / `open -R`.
Every external program is called with an argument list (no shell), so no text can become a command.
"""
from __future__ import annotations

import base64
import os
import subprocess
import tempfile
from pathlib import Path

SERVICE = "Vaelon"
ACCOUNT = "vault-wrap-key"
PREFIX = b"mk1:"


def _keyring():
    try:
        import keyring  # macOS backend: the Security framework (Keychain)
    except ImportError as e:  # a base dependency on macOS; say what to do instead of a bare traceback
        raise OSError("Vaelon keeps its key in the macOS Keychain and needs the 'keyring' package: "
                      "pip install keyring") from e
    return keyring


def _wrap_key(create: bool) -> bytes | None:
    kr = _keyring()
    raw = kr.get_password(SERVICE, ACCOUNT)
    if raw:
        return base64.b64decode(raw)
    if not create:
        return None
    key = os.urandom(32)
    kr.set_password(SERVICE, ACCOUNT, base64.b64encode(key).decode())
    return key


def seal(data: bytes) -> bytes:
    """Encrypt with the Keychain-held key (AES-256-GCM). Raises when the Keychain is not reachable - a secret is never
    written in the clear on a Mac."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = _wrap_key(create=True)
    nonce = os.urandom(12)
    return PREFIX + nonce + AESGCM(key).encrypt(nonce, data, b"vaelon-mac-vault")


def unseal(blob: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if not blob.startswith(PREFIX):
        raise OSError("this secret was not sealed on this Mac")
    key = _wrap_key(create=False)
    if key is None:
        raise OSError("the Keychain item of Vaelon is missing")
    body = blob[len(PREFIX):]
    return AESGCM(key).decrypt(body[:12], body[12:], b"vaelon-mac-vault")


def notify(title: str, text: str) -> bool:
    script = ['on run argv', 'display notification (item 2 of argv) with title (item 1 of argv)', 'end run']
    args = ["osascript"] + [x for line in script for x in ("-e", line)] + [title[:80], text[:300]]
    try:
        return subprocess.run(args, capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def alert(text: str) -> None:
    script = ['on run argv', 'display alert "Vaelon" message (item 1 of argv) as critical', 'end run']
    try:
        subprocess.run(["osascript"] + [x for line in script for x in ("-e", line)] + [text[:500]], capture_output=True,
                       timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        print(text)


def say(text: str, lang: str) -> bytes:
    """WAV (16-bit, 22.05 kHz) from the built-in macOS voice for that language (the default voice if none)."""
    voice = _voice_for(lang)
    with tempfile.TemporaryDirectory() as td:
        src, out = Path(td) / "t.txt", Path(td) / "o.wav"
        src.write_text(text, "utf-8")
        cmd = ["say", "-f", str(src), "-o", str(out), "--data-format=LEI16@22050", "--file-format=WAVE"]
        if voice:
            cmd[1:1] = ["-v", voice]
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        if r.returncode != 0 or not out.exists():
            raise RuntimeError("macOS speech failed: " + r.stderr.decode("utf-8", "replace")[:200])
        return out.read_bytes()


def _voice_for(lang: str) -> str | None:
    """The first installed voice whose locale starts with the language (e.g. 'en_GB', 'bg_BG')."""
    try:
        listing = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in listing.splitlines():
        parts = line.split()
        loc = next((p for p in parts if len(p) == 5 and p[2] == "_"), "")
        if loc.lower().startswith(lang.lower()):
            return " ".join(parts[:parts.index(loc)])
    return None


def open_file(path: str, reveal: bool = False) -> None:
    subprocess.Popen(["open", "-R", path] if reveal else ["open", path])


def is_admin() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0
