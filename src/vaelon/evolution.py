"""Self-rewriting: Vaelon can read and change its own source code - safely.

Pipeline for every change (tool `self_modify`):
  1. path check   - only files inside the vaelon package; the safety core is PROTECTED and can never be rewritten
  2. you approve  - you see the exact diff first (DANGEROUS action, human confirmation)
  3. sandbox test - the change is applied to a temporary copy of the project and the WHOLE test suite runs there
  4. apply        - only if every test passes; the previous version is backed up first
  5. rollback     - `vaelon evolution rollback` (or the tool) restores the last backup at any time

Tests live outside the package, so Vaelon cannot weaken the tests that judge its own changes.
Changes take effect after a restart of `vaelon daemon`.
"""
from __future__ import annotations

import ast
import difflib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import config
from .security import audit, integrity
from .security.policy import PolicyError, Risk
from .tools.registry import tool

PKG = Path(__file__).resolve().parent
REPO = PKG.parent.parent
PROTECTED_DIRS = {"security"}
PROTECTED_FILES = {"evolution.py", "tools/registry.py", "server.py", "config.py", "tools/evolve.py", "hooks.py",
                   "memory.py", "guardian.py", "tools/web.py", "tools/extensions.py", "desktop.py", "agent.py",
                   "company.py", "company_api.py", "journal.py", "settings.py", "mcp.py", "learning.py", "live.py",
                   "conversation.py", "feedback.py", "tools/files.py", "tools/comms.py", "skills.py",
                   "__init__.py", "providers.py", "tools/system.py", "tools/__init__.py", "channels/telegram.py",
                   "tts.py", "voicestream.py", "focus.py", "scheduler.py", "updates.py"}
# Defence in depth only: any module that is imported can in principle patch another at run time - the owner's
# approval of the shown diff (and the full test run) is the real gate.
CARD_LIMIT = 6000  # the approval card shows the whole diff; a bigger change is refused (ask for smaller steps)
MAX_BYTES = 200_000


def is_protected(rel: Path) -> bool:
    return rel.parts[0] in PROTECTED_DIRS or rel.as_posix() in PROTECTED_FILES


def resolve(file: str) -> Path:
    """Return the path RELATIVE to the package, or raise PolicyError."""
    p = Path(file)
    p = (p if p.is_absolute() else PKG / p).resolve()
    try:
        rel = p.relative_to(PKG)
    except ValueError:
        raise PolicyError("self-modification is limited to Vaelon's own package")
    if "__pycache__" in rel.parts or p.suffix not in (".py", ".md"):
        raise PolicyError("only .py and .md files of Vaelon can be changed")
    if is_protected(rel):
        raise PolicyError(f"{rel.as_posix()} is part of the protected safety core")
    return rel


def has_source_checkout() -> bool:
    return (REPO / "tests").is_dir() and (REPO / "pyproject.toml").exists()


def run_tests(root: Path) -> tuple[bool, str]:
    """Run every tests/test_*.py of a project copy in isolated interpreters."""
    out = []
    for t in sorted((root / "tests").glob("test_*.py")):
        try:
            r = subprocess.run([sys.executable, "-I", str(t)], cwd=root, capture_output=True, text=True,
                               timeout=300, errors="replace")
        except subprocess.TimeoutExpired:
            return False, f"{t.name}: timed out"
        tail = (r.stderr or r.stdout)[-1500:]
        out.append(f"{t.name}: {'OK' if r.returncode == 0 else 'FAILED'}")
        if r.returncode != 0:
            return False, "\n".join(out) + "\n" + tail
    return True, "\n".join(out)


def diff(rel: Path, new: str) -> str:
    target = PKG / rel
    old = target.read_text("utf-8").splitlines(keepends=True) if target.exists() else []
    d = "".join(difflib.unified_diff(old, new.splitlines(keepends=True), f"a/{rel.as_posix()}", f"b/{rel.as_posix()}"))
    return d or "(no change)"


def apply_change(rel: Path, new: str, reason: str, runner=run_tests) -> str:
    if not has_source_checkout():
        return "REFUSED: self-modification needs the source checkout (pip install -e .) with its tests/ folder"
    if len(new.encode("utf-8")) > MAX_BYTES:
        return "REFUSED: file too large"
    if rel.suffix == ".py":
        try:
            ast.parse(new)
        except SyntaxError as e:
            return f"REJECTED: syntax error: {e}"
    with tempfile.TemporaryDirectory() as td:
        sandbox = Path(td) / "repo"
        shutil.copytree(REPO / "src", sandbox / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copytree(REPO / "tests", sandbox / "tests", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(REPO / "pyproject.toml", sandbox / "pyproject.toml")
        sb_file = sandbox / "src" / "vaelon" / rel
        sb_file.parent.mkdir(parents=True, exist_ok=True)
        sb_file.write_text(new, "utf-8")
        ok, report = runner(sandbox)
    if not ok:
        audit.log("self_modify_rejected", file=rel.as_posix(), reason=reason)
        return f"REJECTED: tests failed in the sandbox - nothing was changed.\n{report}"
    target = PKG / rel
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_dir = config.HOME / "evolution" / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    if existed:
        shutil.copy2(target, backup_dir / "file.bak")
    (backup_dir / "manifest.json").write_text(json.dumps(
        {"file": rel.as_posix(), "existed": existed, "reason": reason, "time": stamp}, ensure_ascii=False), "utf-8")
    _only_this_changed(rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(new, "utf-8")
    audit.log("self_modify", file=rel.as_posix(), reason=reason, backup=stamp)
    integrity.sign_code()  # the approved change becomes the new trusted baseline
    return f"APPLIED to {rel.as_posix()} (all tests passed; backup {stamp}). Restart `vaelon daemon` to load it."


def _only_this_changed(rel: Path | None) -> None:
    """Signing makes the whole code the new trusted baseline: refuse when anything ELSE was changed meanwhile."""
    ok, problems = integrity.verify_code()
    mine = rel.as_posix() if rel is not None else None
    others = [p for p in problems if p.split(": ", 1)[-1].replace("\\", "/") != mine]
    if others:
        raise PolicyError("other code files changed outside Vaelon (" + "; ".join(others[:3]) + ") - check them and "
                          "run `vaelon integrity sign` yourself first")


def history() -> list[dict]:
    d = config.HOME / "evolution"
    if not d.is_dir():
        return []
    out = []
    for m in sorted(d.glob("*/manifest.json")):
        try:
            out.append(json.loads(m.read_text("utf-8")))
        except Exception:
            pass
    return out


def rollback() -> str:
    d = config.HOME / "evolution"
    entries = sorted(d.glob("*/manifest.json")) if d.is_dir() else []
    if not entries:
        return "nothing to roll back"
    m = entries[-1]
    info = json.loads(m.read_text("utf-8"))
    target = PKG / info["file"]
    _only_this_changed(Path(info["file"]))
    if info["existed"]:
        shutil.copy2(m.parent / "file.bak", target)
    else:
        target.unlink(missing_ok=True)
    shutil.rmtree(m.parent)
    audit.log("self_rollback", file=info["file"], backup=info["time"])
    integrity.sign_code()
    return f"rolled back {info['file']} to the version before {info['time']}. Restart `vaelon daemon`."


@tool("self_list", "List Vaelon's own source files that it is allowed to change", group="evolution")
def self_list(ctx):
    files = [p.relative_to(PKG) for p in PKG.rglob("*") if p.suffix in (".py", ".md") and "__pycache__" not in p.parts]
    return "\n".join(f"{'[protected] ' if is_protected(f) else ''}{f.as_posix()}" for f in sorted(files))


@tool("self_read", "Read one of Vaelon's own source files", {"file": "path relative to the vaelon package"},
      group="evolution")
def self_read(ctx, file):
    p = (PKG / file).resolve()
    if PKG not in p.parents or p.suffix not in (".py", ".md"):
        raise PolicyError("can only read Vaelon's own .py/.md files")
    return p.read_text("utf-8")[:30000]


@tool("self_modify",
      "Rewrite one of Vaelon's own source files (full new content). Applied ONLY after your approval AND all tests pass.",
      {"file": "path relative to the vaelon package", "content": "complete new file content", "reason": "why"},
      risk=Risk.DANGEROUS,
      summary=lambda a: f"SELF-MODIFY {a.get('file')} - {a.get('reason')}\n{_safe_diff(a)}", group="evolution")
def self_modify(ctx, file, content, reason):
    rel = resolve(file)
    if len(diff(rel, str(content))) > CARD_LIMIT:
        return "REFUSED: the change is too big to show in full on the approval card - make it in smaller steps."
    return apply_change(rel, content, reason)


def _safe_diff(a: dict) -> str:
    try:
        d = diff(resolve(str(a.get("file"))), str(a.get("content", "")))
    except PolicyError as e:
        return f"(blocked: {e})"
    if len(d) > CARD_LIMIT:
        return d[:CARD_LIMIT] + f"\n... {len(d) - CARD_LIMIT} more characters NOT SHOWN - this change will be refused."
    return d


@tool("self_rollback", "Undo Vaelon's most recent change to its own code", risk=Risk.DANGEROUS,
      summary=lambda a: "ROLL BACK the last self-modification", group="evolution")
def self_rollback(ctx):
    return rollback()
