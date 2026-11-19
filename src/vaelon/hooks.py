"""Hooks: user Python files in ~/.vaelon/hooks/*.py can observe or veto agent events.

A hook file defines  register(hooks)  and calls  hooks.on("pre_tool", fn).
Events: start, user_message, pre_tool (return a string to VETO), post_tool, final.
"""
from __future__ import annotations

import importlib.util
from collections import defaultdict
from pathlib import Path

from .security import audit


class Hooks:
    def __init__(self):
        self._h = defaultdict(list)

    def on(self, event: str, fn):
        self._h[event].append(fn)

    def fire(self, event: str, **kw):
        """Returns the first non-empty string returned by a handler (veto reason), else None."""
        for fn in self._h[event]:
            try:
                r = fn(**kw)
                if isinstance(r, str) and r:
                    return r
            except Exception as e:
                audit.log("hook_error", event=event, error=str(e))
        return None

    def load_dir(self, d: Path) -> list[str]:
        names = []
        if d.is_dir():
            for f in sorted(d.glob("*.py")):
                from .security import integrity

                if not integrity.is_trusted("hooks", f):
                    audit.log("hook_untrusted_skipped", file=f.name)
                    continue
                spec = importlib.util.spec_from_file_location(f"vaelon_hook_{f.stem}", f)
                try:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    mod.register(self)
                    names.append(f.name)
                except Exception as e:
                    audit.log("hook_load_error", file=f.name, error=str(e))
        return names
