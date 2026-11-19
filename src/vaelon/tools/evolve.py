"""Self-extension: Vaelon can write NEW tools as plugins - AST-validated, human-reviewed, never silent."""
from __future__ import annotations

import ast
import re

from .. import config
from ..security.policy import Risk
from ..security import integrity
from .registry import load_plugins, tool

# A BASIC check only (Python can always find a way round a list like this) - the owner's approval of the code is the
# real safeguard. It catches the obvious: running programs, raw system access, loading code by name.
FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__", "open_unsafe", "getattr", "setattr", "globals", "vars",
                   "breakpoint"}
FORBIDDEN_MODULES = {"subprocess", "ctypes", "socket", "pty", "shutil", "os", "winreg", "importlib", "builtins", "sys",
                     "multiprocessing", "runpy", "marshal", "pickle", "code"}
# Vaelon's own modules a plugin may use are the tool registry and plain helpers - never security, files, the shell,
# company mode or the settings
FORBIDDEN_OWN = ("vaelon.security", "vaelon.tools.system", "vaelon.tools.files", "vaelon.tools.comms", "vaelon.company",
                 "vaelon.settings", "vaelon.config", "vaelon.evolution", "vaelon.server", "vaelon.mcp")


def validate_plugin(code: str) -> list[str]:
    """Static checks. Returns a list of problems (empty = passes). Human review is still required."""
    problems = []
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"syntax error: {e}"]
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name.split(".")[0] in FORBIDDEN_MODULES or a.name.startswith(FORBIDDEN_OWN):
                    problems.append(f"forbidden import: {a.name}")
        elif isinstance(n, ast.ImportFrom) and ((n.module or "").split(".")[0] in FORBIDDEN_MODULES
                                                 or (n.module or "").startswith(FORBIDDEN_OWN) or n.level > 0):
            problems.append(f"forbidden import: {n.module or '.'}")
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FORBIDDEN_CALLS:
            problems.append(f"forbidden call: {n.func.id}")
    if "@tool(" not in code:
        problems.append("plugin must register at least one @tool(...)")
    return problems


@tool("create_tool", "Write a NEW tool plugin (python using @tool from vaelon.tools.registry). The user reviews the code first.",
      {"name": "snake_case file name", "code": "full python source"},
      risk=Risk.DANGEROUS, summary=lambda a: f"INSTALL NEW TOOL '{a.get('name')}':\n{a.get('code')}", group="evolve")
def create_tool(ctx, name, code):
    name = re.sub(r"[^a-z0-9_]", "_", name.lower())[:40]
    problems = validate_plugin(code)
    if problems:
        return "REJECTED by validator: " + "; ".join(problems)
    d = config.HOME / "plugins"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.py").write_text(code, "utf-8")
    integrity.trust("plugins", d / f"{name}.py")  # you approved exactly this code
    loaded = load_plugins(d)
    return f"installed plugin {name}.py (loaded: {loaded}). Delete the file to remove it."
