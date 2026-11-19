"""Scan the source tree for things that must never be published: API keys, tokens, private keys, vault files.

    python scripts/check_secrets.py          # exit code 1 if something is found

Only the kind of finding and its place are printed - never the value itself.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "node_modules", ".next", "out", "dist", "build", "__pycache__", "webui", ".venv", "venv", "versions"}
# certificates / private keys: refused by NAME, before anything is read (they are binary - a text scan would skip them)
FORBIDDEN_SUFFIX = {".pfx", ".p12", ".pvk", ".snk", ".jks", ".keystore", ".key", ".pem", ".spc"}
SKIP_SUFFIX = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".onnx", ".exe", ".dll", ".pyd", ".zip",
               ".lock", ".db", ".enc"}
PATTERNS = {
    "OpenAI-style key": r"\bsk-[A-Za-z0-9_-]{20,}",
    "Groq key": r"\bgsk_[A-Za-z0-9]{30,}",
    "Google key": r"\bAIza[0-9A-Za-z_-]{30,}",
    "Anthropic key": r"\bsk-ant-[A-Za-z0-9_-]{20,}",
    "GitHub token": r"\bgh[pousr]_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{30,}",
    "Slack token": r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
    "AWS access key": r"\bAKIA[0-9A-Z]{16}\b",
    "Twilio SID/key": r"\b(AC|SK)[0-9a-f]{32}\b",
    "Telegram bot token": r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b",
    "private key block": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "bearer token": r"(?i)authorization['\"]?\s*[:=]\s*['\"]bearer\s+[A-Za-z0-9._-]{24,}",
}
FAKE_MARKS = ("abcdefghij", "0123456789", "example", "xxxxxxxx")  # obvious test fixtures, not real keys
FORBIDDEN_FILES = ("api_token", "secrets", "conversation.enc", "memory.db", "profile.enc", ".env")


def main() -> int:
    found = []
    for f in ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in f.relative_to(ROOT).parts) or not f.is_file():
            continue
        rel = f.relative_to(ROOT).as_posix()
        if f.name in FORBIDDEN_FILES:
            found.append((rel, 0, "a private data file that must not be published"))
            continue
        if f.suffix.lower() in FORBIDDEN_SUFFIX:
            found.append((rel, 0, "a certificate or private key file - keep it on its hardware token, never in the repo"))
            continue
        try:
            with f.open("rb") as fh:
                head = fh.read(4)
        except OSError:
            head = b""
        if head[:2] == b"\x30\x82" and f.suffix.lower() not in SKIP_SUFFIX:  # DER / PKCS#12 under another name
            found.append((rel, 0, "looks like a certificate or key container (DER)"))
            continue
        if f.suffix.lower() in SKIP_SUFFIX or f.stat().st_size > 2_000_000:
            continue
        try:
            text = f.read_text("utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for kind, rx in PATTERNS.items():
                m = re.search(rx, line)
                if m and not any(fake in m.group(0).lower() for fake in FAKE_MARKS):
                    found.append((rel, n, kind))
    for rel, n, kind in found:
        print(f"{rel}:{n}: {kind}")
    print(f"{len(found)} possible secret(s) found." if found else "No secrets found.")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
