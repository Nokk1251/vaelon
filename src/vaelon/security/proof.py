"""Proving "I am the real Vaelon" without ever sending the access key.

Another program could sit on Vaelon's port (on Windows a second program can even bind a port that is already in use,
unless the first one asked for exclusive use). Whoever talks to that port first must therefore check that the other
side knows the access key BEFORE trusting it with anything: the asker sends a random nonce, the real core answers
HMAC-SHA256(key, purpose | nonce). The key itself never crosses the connection.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import socket
import sys

NONCE_RX = re.compile(r"[0-9a-f]{32,128}")


def nonce() -> str:
    return secrets.token_hex(16)


def proof(token: str, purpose: str, n: str) -> str:
    return hmac.new(token.encode(), f"{purpose}|{n}".encode(), hashlib.sha256).hexdigest()


def valid_nonce(n) -> bool:
    return isinstance(n, str) and bool(NONCE_RX.fullmatch(n))


def check(token: str, purpose: str, n: str, got) -> bool:
    return isinstance(got, str) and hmac.compare_digest(got.encode("utf-8", "replace"), proof(token, purpose, n).encode())


def exclusive(sock: socket.socket) -> None:
    """Windows: nobody else may bind this address while we hold it (SO_REUSEADDR would let a second program in)."""
    if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
