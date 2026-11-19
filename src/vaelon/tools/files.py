"""Filesystem tools: confined to allowed roots; deletes go to a recoverable trash; writes are undoable."""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from .. import config
from ..security import undo
from ..security.injection import fence
from ..security.policy import PolicyError, Risk, resolve_path, runs_by_itself
from .registry import tool


KNOWN_FOLDERS = {"downloads": "Downloads", "desktop": "Desktop", "documents": "Documents", "pictures": "Pictures",
                 "music": "Music", "videos": "Videos", "home": "", "~": ""}


def _p(ctx, path):
    """'Downloads', '~/Desktop', 'Documents/report.txt' -> the real folder in the user's home."""
    raw = str(path).strip().strip('"').replace("\\", "/")
    parts = [x for x in raw.split("/") if x]
    if parts and not Path(raw).expanduser().is_absolute() and (parts[0].lower().lstrip("~") in KNOWN_FOLDERS or parts[0] == "~"):
        head = KNOWN_FOLDERS.get(parts[0].lower().lstrip("~") or "~", "")
        raw = str(Path.home().joinpath(*([head] if head else []), *parts[1:]))
    elif raw and not Path(raw).expanduser().is_absolute():
        raw = str(Path.home() / raw)  # relative paths are relative to your home, never to Vaelon's own folder
    return resolve_path(raw, ctx.cfg.allowed_roots)


@tool("fs_list", "List a directory", {"path": "directory"}, group="files")
def fs_list(ctx, path):
    d = _p(ctx, path)
    items = sorted(d.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))[:300]
    return "\n".join(f"{'[D]' if i.is_dir() else '   '} {i.name}" for i in items) or "(empty)"


@tool("fs_read", "Read a text file (content is untrusted data)", {"path": "file", "?max_chars": "limit"},
      untrusted=True, group="files")
def fs_read(ctx, path, max_chars=8000):
    p = _p(ctx, path)
    limit = max(1, min(int(max_chars), 200_000))
    with p.open("r", encoding="utf-8", errors="replace") as fh:
        text = fh.read(limit)  # never the whole of a huge file
    return fence(text, f"file:{p.name}")[0]


@tool("fs_search", "Find files by glob (and optionally text inside them)",
      {"root": "directory", "pattern": "glob e.g. *.py", "?contains": "text to grep"}, group="files")
def fs_search(ctx, root, pattern, contains=""):
    pat = str(pattern).replace("\\", "/")
    if not pat or ".." in pat.split("/") or pat.startswith("/") or ":" in pat:
        raise PolicyError("the pattern must stay inside the folder (no '..', no drive or absolute path)")
    out, looked = [], 0
    for f in _p(ctx, root).rglob(pat):
        looked += 1
        if looked > 50_000:
            break
        try:
            f = resolve_path(str(f), ctx.cfg.allowed_roots)  # never a hit outside the allowed folders or in ~/.vaelon
            if not f.is_file():
                continue
            if contains:
                if f.stat().st_size > 5_000_000:
                    continue
                if contains not in f.read_text("utf-8", errors="ignore"):
                    continue
        except (OSError, PolicyError):
            continue
        out.append(str(f))
        if len(out) >= 100:
            break
    return "\n".join(out) or "no matches"


@tool("fs_write", "Create/overwrite a text file (undoable)", {"path": "file", "content": "text"},
      risk=Risk.REVERSIBLE, group="files",  # the card shows WHAT will be written, not only where (head + tail if long)
      summary=lambda a: f"write {a.get('path')} ({len(str(a.get('content', '')))} chars):\n{a.get('content', '')}",
      escalate=lambda a: runs_by_itself(a.get("path", "")))
def fs_write(ctx, path, content):
    p = _p(ctx, path)
    old = p.read_bytes() if p.exists() else None
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, "utf-8")

    def rollback():
        if old is None:
            p.unlink(missing_ok=True)
        else:
            p.write_bytes(old)

    undo.push(f"write {p.name}", rollback)
    return f"wrote {p}"


@tool("fs_move", "Move/rename a file or folder (undoable)", {"src": "from", "dst": "to"},
      risk=Risk.REVERSIBLE, summary=lambda a: f"move {a.get('src')} -> {a.get('dst')}", group="files",
      escalate=lambda a: runs_by_itself(a.get("dst", "")) or runs_by_itself(a.get("src", ""))
      or runs_by_itself(str(Path(str(a.get("dst", ""))) / Path(str(a.get("src", ""))).name)))
def fs_move(ctx, src, dst):
    s, d = _p(ctx, src), _p(ctx, dst)
    d.parent.mkdir(parents=True, exist_ok=True)
    real = Path(shutil.move(str(s), str(d)))  # into an existing folder: the file lands INSIDE it
    undo.push(f"move {s.name}", lambda: shutil.move(str(real), str(s)))
    return f"moved {s} -> {real}"


@tool("fs_delete", "Delete to recoverable trash (undoable)", {"path": "file or folder"},
      risk=Risk.REVERSIBLE, summary=lambda a: f"trash {a.get('path')}", group="files")
def fs_delete(ctx, path):
    p = _p(ctx, path)
    trash = config.HOME / "trash" / time.strftime("%Y%m%d-%H%M%S")
    trash.mkdir(parents=True, exist_ok=True)
    dest = trash / p.name
    shutil.move(str(p), str(dest))
    undo.push(f"delete {p.name}", lambda: shutil.move(str(dest), str(p)))
    return f"moved to trash ({dest}); say 'undo' to restore"


@tool("fs_delete_permanent", "PERMANENTLY delete a file/folder (irreversible)", {"path": "target"},
      risk=Risk.DANGEROUS, summary=lambda a: f"PERMANENTLY DELETE {a.get('path')}", group="files")
def fs_delete_permanent(ctx, path):
    p = _p(ctx, path)
    if p == Path.home() or len(p.parts) <= 2:
        raise PermissionError("refusing to delete a top-level directory")
    shutil.rmtree(p) if p.is_dir() else p.unlink()
    return f"permanently deleted {p}"
