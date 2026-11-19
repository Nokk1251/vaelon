"""Secret / PII redaction (privacy by default)."""
from __future__ import annotations

import re

SECRET_PATTERNS = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)),
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("groq_key", re.compile(r"\bgsk_[A-Za-z0-9]{20,}\b")),
    ("elevenlabs_key", re.compile(r"\bsk_[A-Za-z0-9]{24,}\b")),
    ("openrouter_key", re.compile(r"\bsk-or-[A-Za-z0-9_\-]{20,}")),
    ("cerebras_key", re.compile(r"\bcsk-[A-Za-z0-9]{20,}\b")),
    ("openai_key", re.compile(r"sk-[A-Za-z0-9_\-]{20,}")),
    ("aws_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b")),
    ("google_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")),
    ("bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{20,}")),
    ("password_assign", re.compile(r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|token)\s*[=:]\s*\S{6,}")),
]
PII_PATTERNS = [
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
]
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
PHONE = re.compile(r"(?<!\w)\+?\d[\d ()\-]{7,}\d")


def _luhn(num: str) -> bool:
    d = [int(c) for c in num if c.isdigit()]
    if not 13 <= len(d) <= 19:
        return False
    s = 0
    for i, x in enumerate(reversed(d)):
        if i % 2:
            x *= 2
            if x > 9:
                x -= 9
        s += x
    return s % 10 == 0


def redact(text: str, level: str = "secrets") -> str:
    """level: 'secrets' (keys, tokens, cards, IBAN, SSN) | 'pii' (+ emails, phone numbers)."""
    if not text:
        return text
    for name, rx in SECRET_PATTERNS:
        text = rx.sub(f"[REDACTED:{name}]", text)
    text = CARD.sub(lambda m: "[REDACTED:card]" if _luhn(m.group()) else m.group(), text)
    for name, rx in PII_PATTERNS:
        text = rx.sub(f"[REDACTED:{name}]", text)
    try:
        from .dlp import scrub

        text = scrub(text)  # exact values of YOUR stored keys, whatever their format
    except Exception:
        pass
    if level == "pii":
        text = EMAIL.sub("[REDACTED:email]", text)
        text = PHONE.sub("[REDACTED:phone]", text)
    return text
