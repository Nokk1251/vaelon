"""Coding that checks itself: write -> verify -> read the error -> fix, until it passes (or rounds run out).

Vaelon never reports code as done without running a check on it. When a fix was needed, the lesson is
remembered, so the same mistake is less likely next time.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

from ..security import undo
from ..security.policy import Risk, resolve_path, runs_by_itself
from .registry import tool

CODE_BLOCK = re.compile(r"```[\w+-]*\n(.*?)```", re.S)


def check_file(path: Path, timeout: int = 60) -> tuple[bool, str]:
    """Fast built-in verification by file type. Returns (ok, error_text)."""
    ext = path.suffix.lower()
    if ext == ".py":
        cmd = [sys.executable, "-I", "-m", "py_compile", str(path)]
    elif ext in (".js", ".mjs", ".cjs") and shutil.which("node"):
        cmd = ["node", "--check", str(path)]
    elif ext == ".json":
        import json

        try:
            json.loads(path.read_text("utf-8"))
            return True, ""
        except ValueError as e:
            return False, f"JSON error: {e}"
    elif ext in (".ps1",) and shutil.which("powershell"):
        cmd = ["powershell", "-NoProfile", "-Command",
               "$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('"
               + str(path).replace("'", "''") + "', [ref]$null, [ref]$e); "
               "if ($e) { $e | ForEach-Object { $_.ToString() }; exit 1 }"]
    else:
        return True, "(no automatic check for this file type)"
    from ..security.dlp import safe_env

    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace", env=safe_env())
    return r.returncode == 0, (r.stderr or r.stdout)[-3000:]


def _ask_code(llm, instructions: str, path: Path, current: str, error: str) -> str:
    prompt = (f"You are an exact, careful programmer. Produce the COMPLETE new content of `{path.name}`.\n"
              f"TASK: {instructions}\n")
    if current:
        prompt += f"\nCURRENT FILE:\n```\n{current[:12000]}\n```\n"
    if error:
        prompt += f"\nYOUR PREVIOUS VERSION FAILED THE CHECK WITH:\n{error}\nFix the cause, not the symptom.\n"
    prompt += "\nReply with ONE fenced code block containing the whole file and nothing else."
    reply = llm.chat([{"role": "user", "content": prompt}])
    m = CODE_BLOCK.search(reply)
    return (m.group(1) if m else reply).rstrip() + "\n"


@tool("code_task",
      "Write or change a code file and VERIFY it (compile/syntax check), fixing errors automatically. Undoable.",
      {"path": "file to create or edit", "instructions": "what the code must do", "?max_rounds": "fix attempts (default 3)"},
      risk=Risk.REVERSIBLE, summary=lambda a: f"write and verify code in {a.get('path')}\nTASK: {a.get('instructions', '')}", group="coding",
      escalate=lambda a: runs_by_itself(a.get("path", "")))
def code_task(ctx, path, instructions, max_rounds=3):
    agent = ctx.extra.get("agent")
    if agent is None:
        return "ERROR: coding needs the agent's language model"
    from .files import _p

    p = _p(ctx, path)  # the same place fs_write would use (a relative path goes under the home folder)
    original = p.read_text("utf-8") if p.exists() else None
    # the way back exists BEFORE the first write: a failure in a later round can never lose the original
    undo.push(f"code {p.name}", (lambda: p.write_text(original, "utf-8")) if original is not None
              else (lambda: p.unlink(missing_ok=True)))
    current, error, log, ok, log_error = original or "", "", [], False, ""
    for round_no in range(1, max(1, min(int(max_rounds), 6)) + 1):
        code = _ask_code(agent.llm, instructions, p, current, error)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(code, "utf-8")
        ok, error = check_file(p)
        log.append(f"round {round_no}: {'passed' if ok else 'failed'}")
        if ok:
            if round_no > 1:  # learn from the fix
                ctx.memory.add(f"Lesson (coding {p.suffix}): first attempt failed with "
                               f"'{log_error[:160]}' - check this earlier next time.", kind="lesson")
            break
        current, log_error = code, error.strip().splitlines()[-1] if error.strip() else "error"
    lines = len(p.read_text("utf-8").splitlines())
    status = "VERIFIED" if ok else "NOT VERIFIED - last error:\n" + error[-1200:]
    return f"{status}\n{p} ({lines} lines). " + "; ".join(log) + ". Say 'undo' to revert."
