"""Human confirmation the model cannot forge.

The approver callback belongs to the *interface* (CLI prompt, Telegram reply, UI button).
Tool arguments never contain a 'confirmed' flag, so the model cannot self-approve.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

# characters that can hide or reorder what a person reads: controls (not newline / tab), ESC sequences, bidi
# overrides, zero-width marks, soft hyphen
_HIDDEN = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x84\x86-\x9f\u00ad\u115f\u1160\u200b-\u200f\u202a-\u202e"
                     r"\u2060-\u2064\u2066-\u2069\u2800\u3164\ufeff\uffa0]")
_LINE_BREAKS = re.compile(r"\r\n?|[\u0085\u2028\u2029]")  # every way of breaking a line counts as one
CAP, HEAD, TAIL = 1500, 900, 300


def shown(text: str) -> str:
    """The text of an approval card, as a person will really read it: hidden characters removed (and said so),
    runs of blank lines / spaces collapsed, and when it is long the START and the END are shown (a payload likes to
    hide at the end)."""
    text = _LINE_BREAKS.sub("\n", str(text))
    cleaned, n = _HIDDEN.subn("", text)
    # blank lines made of any spaces (also no-break and wide ones) collapse: padding cannot push a line out of view
    cleaned = re.sub(r"\n(?:[^\S\n]*\n){2,}", "\n\n", cleaned)  # anchored at a break: linear, never O(n^2)
    cleaned = re.sub(r"[^\S\n]{8,}", "    ", cleaned)
    if len(cleaned) > CAP:
        cleaned = (cleaned[:HEAD] + f"\n... {len(cleaned) - HEAD - TAIL} characters not shown ...\n"
                   + cleaned[-TAIL:])
    if n:  # said FIRST, so the end of the text stays the end of the card
        cleaned = f"[{n} hidden character(s) removed]\n" + cleaned
    return cleaned


@dataclass
class ConfirmRequest:
    tool: str
    summary: str  # exact human-readable description of what will happen (already passed through shown())
    tainted: bool = False  # untrusted content was read in this turn
    note: str = ""  # Vaelon's OWN remark (why it asks) - kept apart, so text from the model can never fake it


Approver = Callable[[ConfirmRequest], bool]


def deny_all(_: ConfirmRequest) -> bool:
    return False


def cli_approver(req: ConfirmRequest) -> bool:
    import sys

    if not sys.stdin or not sys.stdin.isatty():
        return False
    flag = "\n  [!] untrusted content was read this turn - double-check" if req.tainted else ""
    body = "\n".join("  | " + line for line in shown(req.summary).splitlines())
    note = f"\n  -- Vaelon: {req.note}" if req.note else ""
    print(f"\n[CONFIRM] {req.tool}\n{body}{note}{flag}")
    return input("  Allow? [y/N] ").strip().lower() in ("y", "yes", "da", "да")
