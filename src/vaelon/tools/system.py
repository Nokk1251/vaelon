"""System tools: shell, apps, processes, time."""
from __future__ import annotations

import os
import platform
import subprocess
import sys
import time

from ..security.injection import fence
from ..security.policy import Risk
from .registry import tool


@tool("now", "Current local date and time", group="system")
def now(ctx):
    return time.strftime("%Y-%m-%d %H:%M:%S %A")


@tool("system_info", "OS, CPU, RAM, disk summary", group="system")
def system_info(ctx):
    info = [f"OS: {platform.platform()}", f"Python: {sys.version.split()[0]}"]
    try:
        import psutil

        info += [f"CPU: {psutil.cpu_percent(interval=0.3)}%",
                 f"RAM: {psutil.virtual_memory().percent}%",
                 f"Disk: {psutil.disk_usage(os.path.expanduser('~')).percent}%"]
    except ImportError:
        info.append("(pip install psutil for live stats)")
    return "\n".join(info)


@tool("list_processes", "Top processes by memory", group="system")
def list_processes(ctx):
    import psutil

    ps = sorted(psutil.process_iter(["pid", "name", "memory_percent"]),
                key=lambda p: p.info["memory_percent"] or 0, reverse=True)[:15]
    return "\n".join(f"{p.info['pid']:>7} {p.info['name']} {p.info['memory_percent']:.1f}%" for p in ps)


@tool("kill_process", "Terminate a process by pid", {"pid": "process id"}, risk=Risk.DANGEROUS,
      summary=lambda a: f"KILL process {a.get('pid')}", group="system")
def kill_process(ctx, pid):
    import psutil

    p = psutil.Process(int(pid))
    name = p.name()
    p.terminate()
    return f"terminated {name} ({pid})"


@tool("open_app", "Open an application, file or URL with the OS default handler", {"target": "app/file/url"},
      risk=Risk.DANGEROUS, summary=lambda a: f"OPEN {a.get('target')}", group="system")
def open_app(ctx, target):
    if sys.platform.startswith("win"):
        os.startfile(target)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target])
    return f"opened {target}"


@tool("run_command", "Run a shell command (ALWAYS needs user approval). Output is untrusted.",
      {"command": "shell command", "?cwd": "working dir", "?timeout": "seconds (max 300)"},
      risk=Risk.DANGEROUS, untrusted=True, group="system",
      summary=lambda a: f"RUN: {a.get('command')}" + (f"\nIN FOLDER: {a.get('cwd')}" if a.get("cwd") else ""))
def run_command(ctx, command, cwd="", timeout=60):
    from ..security import dlp
    from ..security.policy import PolicyError, resolve_path

    if dlp.SECRET_ACCESS.search(str(command)):
        raise PolicyError("commands may not access Vaelon's key vault or Windows DPAPI")
    folder = str(resolve_path(str(cwd), ctx.cfg.allowed_roots)) if cwd else None
    limit = max(1, min(int(timeout), 300))
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    posix = sys.platform != "win32"
    proc = subprocess.Popen(command, shell=True, cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            errors="replace", env=dlp.safe_env(), creationflags=flags,
                            start_new_session=posix)  # macOS / Linux: its own process group, stopped as a whole
    try:
        so, se = proc.communicate(timeout=limit)
    except subprocess.TimeoutExpired:
        # shell=True: killing cmd.exe alone leaves its children holding the pipes - stop the whole tree
        if posix:
            import signal

            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
        else:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        try:
            so, se = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            so, se = "", ""
        return fence(f"stopped after {limit} s (time limit)\n{(so or '')[-4000:]}", "command_output")[0]
    out = f"exit={proc.returncode}\n{(so or '')[-6000:]}\n{(se or '')[-2000:]}"
    return fence(out, "command_output")[0]
