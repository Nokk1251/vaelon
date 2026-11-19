"""Shared undo stack: act now, reverse on request.

Company mode (found by the code review): an entry remembers WHO did it, in WHICH company and that company's folder.
`undo()` takes back only the caller's own last action in the company that is open, and restores it into the folder
where it was done - never one company's snapshot into another, never the owner's action by someone else.
"""
from __future__ import annotations

import threading
from typing import Callable

_MAX = 40
_stack: list[tuple[str, Callable[[], object], tuple, object]] = []
_lock = threading.Lock()


def _where():
    try:
        from .. import company

        return company.key(), company.data_dir()
    except Exception:
        return ("", ""), None


def push(label: str, fn: Callable[[], object]) -> None:
    key, folder = _where()
    with _lock:
        _stack.append((label, fn, key, folder))
        del _stack[:-_MAX]


def undo() -> str:
    key, _ = _where()
    with _lock:
        n = next((i for i in range(len(_stack) - 1, -1, -1) if _stack[i][2] == key), None)
        if n is None:
            return "Nothing to undo."
        entry = _stack.pop(n)
    label, fn, _key, folder = entry
    try:
        from .. import company

        if folder is not None:
            with company.use_dir(folder):
                fn()
        else:
            fn()
        return f"Undone: {label}"
    except Exception as e:
        with _lock:
            _stack.insert(min(n, len(_stack)), entry)  # not lost: it can be tried again
        return f"Could not undo '{label}': {e}"


def pending() -> list[str]:
    key, _ = _where()
    with _lock:
        return [label for label, _f, k, _d in reversed(_stack) if k == key]
