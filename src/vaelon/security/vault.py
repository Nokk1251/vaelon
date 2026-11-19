"""Vault: encryption at rest for Vaelon's private data.

- One random 256-bit master key per machine. On Windows it is sealed with DPAPI (only YOUR Windows account on
  THIS computer can unseal it - copying the file elsewhere is useless). On macOS/Linux it is a 0600 file.
- Data: AES-256-GCM (authenticated encryption - any tampering is detected) via the audited `cryptography` library.
- Search over encrypted data: "blind index" tokens = HMAC-SHA256 of words, so the database never contains your
  words in plain text, yet memory search still works.
- Separate keys are derived per purpose with HKDF (encryption / search index / integrity / audit).

Why not "encrypt the source code"? Vaelon is open source - hiding code adds no security (anyone can read the
public repo). What protects you is: encrypted private data, signed integrity checks of the code that runs
(security/integrity.py), and refusing to run plugins you did not approve.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import sys
from functools import lru_cache
from pathlib import Path

from .. import config

PREFIX = "enc1:"
# Format tags of data version 1. They are mixed into every key and every encrypted record: NEVER change a
# single byte, or nothing that was stored before can be read again. (Hex, because they are bytes, not words.)
AAD = bytes.fromhex("756c74726f6e2d7631")


def _secrets_dir() -> Path:
    d = config.HOME / "secrets"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------- Windows DPAPI (no extra dependency) ----------
# Extra "entropy" binds every sealed blob to Vaelon: generic DPAPI dumping tools that decrypt a user's blobs in bulk
# (without knowing this value) get nothing. It is fixed, not random, so it can never be lost (a lost value would
# make your memory unreadable). Older blobs sealed without it are read once and re-sealed automatically.
ENTROPY = bytes.fromhex("554c54524f4e2d7661756c742d76327c7365616c65642d73656372657473")


def _dpapi(data: bytes, protect: bool, entropy: bytes | None = None) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    ent = None
    if entropy:
        ebuf = ctypes.create_string_buffer(entropy, len(entropy))
        ent = ctypes.byref(BLOB(len(entropy), ctypes.cast(ebuf, ctypes.POINTER(ctypes.c_char))))
    blob_out = BLOB()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(blob_in), None, ent, None, None, 0x1, ctypes.byref(blob_out)):  # UI_FORBIDDEN
        raise OSError("DPAPI failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def seal(data: bytes) -> bytes:
    """Windows: DPAPI (bound to the Windows account). macOS: AES-GCM with a key held in the Keychain."""
    if sys.platform == "win32":
        return _dpapi(data, True, ENTROPY)
    if sys.platform == "darwin":
        from .. import platform_mac

        return platform_mac.seal(data)
    return data  # other systems: protected only by the file permissions (0600) - said in PRIVACY.md


def unseal(data: bytes) -> bytes:
    if sys.platform == "darwin":
        from .. import platform_mac

        return platform_mac.unseal(data)
    if sys.platform != "win32":
        return data
    try:
        return _dpapi(data, False, ENTROPY)
    except OSError:
        return _dpapi(data, False)  # blob from an older version (no entropy)


def _atomic_write(p: Path, blob: bytes) -> None:
    """Write to a temp file, flush to disk, then rename over the target: a crash can never leave half a key."""
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(blob)
        f.flush()
        os.fsync(f.fileno())
    replace(tmp, p)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass



def replace(tmp, target) -> None:
    """os.replace with a few retries: on Windows it fails while another thread (the reminder thread, a parallel task)
    has the target open for reading - a save must not be lost to that moment."""
    import time as _time

    for attempt in range(6):
        try:
            os.replace(tmp, target)
            return
        except PermissionError:
            if attempt == 5:
                raise
            _time.sleep(0.03 * (attempt + 1))

def write_secret(name: str, data: bytes) -> None:
    _atomic_write(_secrets_dir() / name, seal(data))


def read_secret(name: str) -> bytes | None:
    p = _secrets_dir() / name
    if not p.exists():
        return None
    raw = p.read_bytes()
    if sys.platform == "win32":
        try:
            return _dpapi(raw, False, ENTROPY)
        except OSError:
            val = _dpapi(raw, False)  # older blob: upgrade it in place
            try:
                _atomic_write(p, seal(val))
            except OSError:
                pass
            return val
    if sys.platform == "darwin":
        return unseal(raw)
    return raw


@lru_cache(maxsize=4)
def _master(home: str) -> bytes:
    key = read_secret("master.key")
    if key is None:
        key = os.urandom(32)
        write_secret("master.key", key)
    return key


HKDF_SALT = bytes.fromhex("756c74726f6e2d686b64662d73616c74")  # format tag, see AAD


def subkey(purpose: str) -> bytes:
    """HKDF-SHA256 (RFC 5869) derived key for one purpose."""
    prk = hmac.new(HKDF_SALT, _master(str(config.HOME)), hashlib.sha256).digest()
    return hmac.new(prk, purpose.encode() + b"\x01", hashlib.sha256).digest()


def available() -> bool:
    try:
        import cryptography  # noqa: F401
        return True
    except ImportError:
        return False


def encrypt_text(text: str) -> str:
    if not available():  # never store personal data in the clear just because a library is missing
        raise RuntimeError('encryption needs the "cryptography" package: pip install cryptography')
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    ct = AESGCM(subkey("data")).encrypt(nonce, text.encode("utf-8"), AAD)
    return PREFIX + base64.b64encode(nonce + ct).decode()


def decrypt_text(value: str, allow_plain: bool = False) -> str:
    """Decrypt (and so authenticate) a stored value. A value WITHOUT the prefix is refused: plain text in an encrypted
    store would let someone who can write the file forge it without the key (white-hat test 2026-11-18). Only the
    one-time migrations of really old plain data pass `allow_plain`."""
    if not value.startswith(PREFIX):
        if allow_plain:
            return value
        raise ValueError("this value is not encrypted - refused")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    raw = base64.b64decode(value[len(PREFIX):])
    return AESGCM(subkey("data")).decrypt(raw[:12], raw[12:], AAD).decode("utf-8")


def blind_tokens(text: str) -> list[str]:
    """Searchable but unreadable: HMAC of each word, plus a 4-letter prefix token so inflected
    forms still match (Варна / Варненски, learn / learning)."""
    k = subkey("index")
    out = []
    for w in set(re.findall(r"\w+", text.lower())):
        out.append("w" + hmac.new(k, w.encode(), hashlib.sha256).hexdigest()[:16])
        if len(w) >= 4:
            out.append("p" + hmac.new(k, b"p:" + w[:4].encode(), hashlib.sha256).hexdigest()[:16])
    return out
