"""Extensions manager: list, enable, disable and inspect Vaelon's plugins (~/.vaelon/plugins)."""
from __future__ import annotations

import shutil

from .. import config
from ..security import undo
from ..security.policy import Risk
from .evolve import validate_plugin
from .registry import tool


def _dirs():
    on = config.HOME / "plugins"
    off = on / "disabled"
    return on, off


@tool("extension_list", "List Vaelon's extensions (plugins), their state and a safety check of each", group="evolution")
def extension_list(ctx):
    on, off = _dirs()
    rows = []
    for state, d in (("enabled", on), ("disabled", off)):
        for f in sorted(d.glob("*.py")) if d.is_dir() else []:
            problems = validate_plugin(f.read_text("utf-8", errors="replace"))
            rows.append(f"{f.stem} [{state}] {'OK' if not problems else 'WARNING: ' + '; '.join(problems)}")
    return "\n".join(rows) or "no extensions installed (Vaelon can write one with create_tool)"


def _move(name: str, enable: bool) -> str:
    import re

    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,60}", name):
        return "an extension name is letters, digits, '_' or '-' only"
    on, off = _dirs()
    src, dst = (off, on) if enable else (on, off)
    f = src / f"{name}.py"
    if not f.exists():
        return f"no {'disabled' if enable else 'enabled'} extension named {name}"
    dst.mkdir(parents=True, exist_ok=True)
    shutil.move(str(f), str(dst / f.name))
    undo.push(f"{'enable' if enable else 'disable'} {name}", lambda: shutil.move(str(dst / f.name), str(f)))
    return f"{name} {'enabled' if enable else 'disabled'}. Restart Vaelon to apply."


@tool("extension_enable", "Enable a disabled extension", {"name": "extension name"}, risk=Risk.DANGEROUS,
      summary=lambda a: f"ENABLE extension {a.get('name')} (it will run as code on this PC)", group="evolution")
def extension_enable(ctx, name):
    return _move(str(name), True)


@tool("extension_disable", "Disable an extension", {"name": "extension name"}, risk=Risk.REVERSIBLE, group="evolution")
def extension_disable(ctx, name):
    return _move(str(name), False)
