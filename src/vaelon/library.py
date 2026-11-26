"""Ask your folder (issue #30): the user picks folders; Vaelon reads the documents in them (PDF, Word, Excel,
PowerPoint, text, Markdown, CSV, HTML) into a local, ENCRYPTED index of short passages and answers questions from the
best passages, naming the file each one came from.

- Search is keyword search (BM25) on this computer - no model download, nothing sent anywhere.
- Folders: only inside the allowed folders, never the home folder itself, a drive root, app-data areas (AppData,
  Library, dot-folders) or system folders. Inside them, hidden files, links, junctions, hard links, sensitive names
  (keys, passwords, recovery codes, wallets ...), private keys and seed phrases are skipped; secrets that look like keys
  or card numbers inside a document are blanked before indexing.
- Every file is OPENED first and checked afterwards (its real path and link count from the open handle), then parsed
  from those bytes: a file swapped for a link in between is not read. Office files are checked for zip bombs.
- Document text is OUTSIDE content: the tool that returns passages is untrusted (the task is tainted) and private (the
  user's own data), passages are fenced, and addresses inside them are never treated as given by the user.
- Reading a folder never blocks questions: one scan at a time, outside the index lock; questions use the last index.
- The index lives in library.enc (vault-encrypted); removing a folder removes its passages; a folder that is gone or no
  longer allowed is not searched and its passages are dropped at the next refresh.
"""
from __future__ import annotations

import html
import json
import math
import os
import re
import stat
import string
import sys
import threading
import time
import unicodedata
from collections import Counter
from pathlib import Path

from . import config
from .security import vault
from .security.policy import SENSITIVE_NAMES, PolicyError, _config_place, odd_path, resolve_path
from .security.redact import CARD, SECRET_PATTERNS, _luhn

FILE = "library.enc"
EXTS = {".txt", ".md", ".pdf", ".docx", ".xlsx", ".pptx", ".csv", ".rtf", ".log", ".json", ".html", ".htm"}
MAX_FOLDERS = 20
MAX_FILES = 3000  # per folder
MAX_FILE_BYTES = 40 * 1024 * 1024
MAX_FILE_CHARS = 400_000
MAX_TOTAL_CHARS = 12_000_000  # all folders together (the encrypted index stays a few tens of MB at most)
PASSAGE = 900
OVERLAP = 150
TOP = 6
PRIVATE_KEY_RX = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----|PuTTY-User-Key-File-\d")
SEED_RX = re.compile(r"(?i)\b(seed|recovery|mnemonic)\s+(phrase|words)\b")
SECRET_NAME = re.compile(
    r"(?<![a-z])(pass(word|wd|code)s?|secrets?|credentials?|tokens?|api[ _-]?keys?|apikeys?|access[ _-]?keys?"
    r"|private[ _-]?keys?|recovery[ _-]?(codes?|keys?|phrase|kit)|backup[ _-]?codes?|2fa|mfa|otp|seed[ _-]?(phrase|words)"
    r"|aws[ _-]?(access|secret|keys?|credentials?)|mnemonic|wallet|keystore|keychain|bitwarden|1password|lastpass|keepass(xc)?|dashlane|nordpass|enpass|authy"
    r"|authenticator|парол\w*)(?![a-z])")
SKIP_DIRS = {"appdata", "application data", "node_modules", "__pycache__", "site-packages", "local storage",
             "session storage", "leveldb", "indexeddb", "$recycle.bin", "system volume information"}

_lock = threading.RLock()  # the index in memory and on disk (short holds only)
_scan_lock = threading.Lock()  # one folder scan at a time (long; never held together with a question)
_cache: dict = {"stamp": None, "data": None, "index": None}


class LibraryError(Exception):
    pass


# --- storage -------------------------------------------------------------------------------------------------------

def _path() -> Path:
    return config.HOME / FILE


def load() -> dict:
    """{"folders": [...], "passages": [...]} - empty when there is none or it cannot be read (it can be rebuilt)."""
    p = _path()
    with _lock:
        stamp = p.stat().st_mtime_ns if p.exists() else None
        if _cache["stamp"] == stamp and _cache["data"] is not None:
            return _cache["data"]
        data = {"folders": [], "passages": []}
        if p.exists():
            try:
                data = json.loads(vault.decrypt_text(p.read_text("utf-8").strip()))
            except Exception:
                data = {"folders": [], "passages": [], "unreadable": True}
        _cache.update(stamp=stamp, data=data, index=None)
        return data


def _store(data: dict) -> None:
    data.pop("unreadable", None)
    config.HOME.mkdir(parents=True, exist_ok=True)
    p = _path()
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(vault.encrypt_text(json.dumps(data, ensure_ascii=False)), "utf-8")
    vault.replace(tmp, p)
    _cache.update(stamp=p.stat().st_mtime_ns, data=data, index=None)


# --- which folders may be added --------------------------------------------------------------------------------------

def _system_places() -> list[Path]:
    names = ("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData")
    out = [Path(os.environ[n]) for n in names if os.environ.get(n)]
    if sys.platform != "win32":
        out += [Path(x) for x in ("/System", "/Applications", "/usr", "/etc", "/bin", "/sbin", "/opt")]
    return [x.resolve() for x in out]


def check_folder(cfg, raw: str) -> Path:
    """The folder as it will be indexed, or LibraryError / PolicyError with the reason."""
    raw = str(raw).strip()
    if not raw or not Path(raw).expanduser().is_absolute():
        raise LibraryError("give the full path of the folder (for example C:\\Users\\you\\Documents\\Contracts)")
    folder = resolve_path(raw, cfg.allowed_roots)
    if not folder.is_dir():
        raise LibraryError("that is not a folder")
    home = Path.home().resolve()
    if folder == home or folder in home.parents or folder.parent == folder:
        raise LibraryError("pick a specific folder - not the whole home folder or a drive (too much private data)")
    if _config_place(folder.as_posix().lower().rstrip("/") + "/") or folder.name.lower() in SKIP_DIRS:
        raise LibraryError("app settings and hidden folders cannot be added (they hold tokens and passwords)")
    for place in _system_places():
        if folder == place or place in folder.parents:
            raise LibraryError("system folders cannot be added")
    return folder


# --- reading files -------------------------------------------------------------------------------------------------

_SCRIPT = re.compile(r"<\s*(script|style)\b")
_ASCII_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)


def strip_html(raw: str) -> str:
    """Text of an HTML page in linear time (a regular expression was quadratic on unclosed tags - red team R2)."""
    low, out, i, n = raw.translate(_ASCII_LOWER), [], 0, len(raw)  # same length as raw: indexes stay valid
    while i < n:
        lt = raw.find("<", i)
        if lt < 0:
            out.append(raw[i:])
            break
        out.append(raw[i:lt])
        gt = raw.find(">", lt + 1)
        if gt < 0:
            break  # an unclosed tag: the rest is not text
        m = _SCRIPT.match(low, lt, gt + 1)
        i = gt + 1
        if m:
            end = low.find("</" + m.group(1), i)
            close = raw.find(">", end) if end >= 0 else -1
            i = n if close < 0 else close + 1
        out.append(" ")
    return html.unescape(" ".join("".join(out).split()))


def blank_secrets(text: str) -> tuple[str, int]:
    """Keys, tokens, passwords written as "password: ..." and card numbers are blanked before indexing."""
    count = 0
    for _name, rx in SECRET_PATTERNS:
        text, k = rx.subn("[secret hidden]", text)
        count += k

    def card(m):
        nonlocal count
        if _luhn(m.group(0)):
            count += 1
            return "[card number hidden]"
        return m.group(0)
    return CARD.sub(card, text), count


def _final_path(fd: int) -> str:
    """The real path of an open file, from the handle (not from the name, which can change meanwhile)."""
    if sys.platform == "win32":
        import ctypes
        import msvcrt
        from ctypes import wintypes

        h = msvcrt.get_osfhandle(fd)
        buf = ctypes.create_unicode_buffer(32768)
        fn = ctypes.windll.kernel32.GetFinalPathNameByHandleW
        fn.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
        n = fn(h, buf, 32768, 0)
        if not n or n >= 32768:
            raise OSError("cannot tell where the file really is")
        real = buf.value
        if real.startswith("\\\\?\\UNC\\"):
            raise OSError("a network file")
        return real[4:] if real.startswith("\\\\?\\") else real
    if sys.platform == "darwin":
        import fcntl

        return fcntl.fcntl(fd, 50, b"\0" * 1024).split(b"\0", 1)[0].decode()  # F_GETPATH
    return os.readlink(f"/proc/self/fd/{fd}")


def open_checked(p: Path, folder: Path, roots: list[str]) -> bytes:
    """Open first, check afterwards, read from the SAME handle: the bytes of a regular file with one name that
    really lies inside FOLDER and the allowed folders (a link, a junction, a hard link or a swap in between fails)."""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(p, flags)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise LibraryError("not a regular file")
        if st.st_nlink > 1:
            raise LibraryError("a hard link (the same file under another name elsewhere)")
        if st.st_size > MAX_FILE_BYTES:
            raise LibraryError("too big")
        real = resolve_path(_final_path(fd), roots)
        if folder not in real.parents:
            raise LibraryError("points outside the folder")
        chunks, left = [], st.st_size + 1
        while left > 0:
            b = os.read(fd, min(left, 1 << 20))
            if not b:
                break
            chunks.append(b)
            left -= len(b)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _read(p: Path, folder: Path, roots: list[str]) -> str:
    from .tools.perception import read_bytes

    data = open_checked(p, folder, roots)
    ext = p.suffix.lower()
    if ext in (".html", ".htm"):
        return strip_html(data[:MAX_FILE_CHARS * 8].decode("utf-8", errors="replace"))[:MAX_FILE_CHARS]
    return read_bytes(data, ext, MAX_FILE_CHARS)


def _passages(text: str) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text.replace("\x00", " ")).strip()
    out, i = [], 0
    while i < len(text):
        end = min(len(text), i + PASSAGE)
        if end < len(text):  # end at a sentence or a line break when one is near
            cut = max(text.rfind(". ", i + PASSAGE // 2, end), text.rfind("\n", i + PASSAGE // 2, end))
            if cut > i:
                end = cut + 1
        chunk = text[i:end].strip()
        if len(chunk) > 20:
            out.append(chunk)
        if end >= len(text):
            break
        i = max(end - OVERLAP, i + 1)
    return out


CLOUD_ONLY = 0x400000 | 0x40000 | 0x1000  # RECALL_ON_DATA_ACCESS | RECALL_ON_OPEN | OFFLINE (OneDrive placeholders)
HIDDEN_ATTRS = 0x2 | 0x4  # FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM


def _attrs(p: Path) -> int:
    try:
        return getattr(os.lstat(p), "st_file_attributes", 0)
    except OSError:
        return 0


def _is_junction(p: Path) -> bool:
    """A Windows junction (os.path.isjunction exists only from Python 3.12)."""
    if hasattr(os.path, "isjunction"):
        return os.path.isjunction(p)
    if sys.platform == "win32":
        try:
            return getattr(os.lstat(p), "st_reparse_tag", 0) == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)
        except OSError:
            return True  # cannot tell: do not enter
    return False


def _secret_name(rel: str) -> bool:
    low = rel.lower()
    name = low.rsplit("/", 1)[-1]
    stem = name.rsplit(".", 1)[0]
    return name in SENSITIVE_NAMES or stem in SENSITIVE_NAMES or bool(SECRET_NAME.search(low.replace("_", " ")))


def _walk(folder: Path):
    """(relative path, absolute path, skip reason or "") for every document under FOLDER - links, junctions, hidden
    and app-data folders are not entered."""
    count = extra = 0
    for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
        here = Path(dirpath)
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d.lower() not in SKIP_DIRS
                             and not (here / d).is_symlink() and not _is_junction(here / d)
                             and not _attrs(here / d) & HIDDEN_ATTRS)
        for name in sorted(filenames):
            p = here / name
            if p.suffix.lower() not in EXTS:
                continue  # not a document: not even counted
            if count >= MAX_FILES:
                extra += 1  # only counted: a huge tree never fills memory with reasons
                continue
            rel = p.relative_to(folder).as_posix()
            attrs = _attrs(p)
            if name.startswith(".") or p.is_symlink() or attrs & HIDDEN_ATTRS:
                yield rel, p, "hidden or a link"
                continue
            if attrs & CLOUD_ONLY:
                yield rel, p, "only in the cloud (not downloaded to this computer)"
                continue
            if _secret_name(rel):
                yield rel, p, "sensitive name"
                continue
            count += 1
            yield rel, p, ""
    if extra:
        yield f"({extra} more documents)", None, f"not read - at most {MAX_FILES} documents per folder"


# --- index ---------------------------------------------------------------------------------------------------------

def _scan(entry: dict, data: dict, roots: list[str]) -> dict:
    """Bring one folder's passages in DATA up to date (only changed files are read again). Returns counts."""
    folder = Path(entry["path"])
    if not folder.is_dir():
        raise LibraryError(f"the folder is gone: {folder}")
    known = entry.get("files", {})
    seen, skipped, read = {}, [], 0
    mine, keep = {}, []
    for x in data["passages"]:
        if x["d"] == entry["path"]:
            mine.setdefault(x["f"], []).append(x)
        else:
            keep.append(x)
    total = sum(len(x["t"]) for x in keep)
    for rel, p, why in _walk(folder):
        if why or p is None:
            skipped.append((rel, why))
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        stamp = [st.st_mtime_ns, st.st_size]
        if known.get(rel, {}).get("s") == stamp and rel in mine:
            parts = mine[rel]
        else:
            try:
                text = _read(p, folder, roots)
            except (LibraryError, PolicyError) as e:
                skipped.append((rel, str(e)))
                continue
            except Exception as e:  # a damaged, locked or hostile file never stops the rest
                skipped.append((rel, f"could not be read ({type(e).__name__}: {str(e)[:60]})"))
                continue
            if PRIVATE_KEY_RX.search(text):
                skipped.append((rel, "holds a private key"))
                continue
            if SEED_RX.search(text):
                skipped.append((rel, "looks like a wallet seed or recovery phrase"))
                continue
            text, k = blank_secrets(text)
            parts = [{"d": entry["path"], "f": rel, "n": n, "t": t} for n, t in enumerate(_passages(text))]
            read += 1
            known = {**known, rel: {**known.get(rel, {}), "h": k}}
        size = sum(len(x["t"]) for x in parts)
        if total + size > MAX_TOTAL_CHARS:
            skipped.append((rel, "the library is full"))
            continue
        total += size
        keep.extend(parts)
        seen[rel] = {"s": stamp, "n": len(parts), "h": known.get(rel, {}).get("h", 0)}
    changed = bool(read) or set(seen) != set(entry.get("files", {})) or "unavailable" in entry
    data["passages"] = keep
    hidden = sum(v.get("h", 0) for v in seen.values())
    entry.update(files=seen, skipped=len(skipped), skipped_sample=[f"{r}: {w}" for r, w in skipped[:10]],
                 hidden=hidden, updated=time.strftime("%Y-%m-%d %H:%M"))
    entry.pop("unavailable", None)
    return {"folder": entry["path"], "files": len(seen), "read": read, "skipped": len(skipped), "hidden": hidden,
            "changed": changed}


def _copy(data: dict) -> dict:
    return json.loads(json.dumps(data))


def _merge(work: dict, scanned: set[str]) -> None:
    """Store WORK, keeping what happened meanwhile: a folder removed during the scan stays removed."""
    with _lock:
        now = load()
        if now.get("unreadable") and _path().exists():
            raise LibraryError("the library file cannot be read right now - nothing was changed")
        present = {f["path"] for f in now["folders"]}
        work["folders"] = [f for f in work["folders"] if f["path"] in present or f["path"] in scanned]
        mine = {f["path"] for f in work["folders"]}
        for f in now["folders"]:  # added meanwhile (e.g. by the command line): keep it and its passages
            if f["path"] not in mine:
                work["folders"].append(f)
                work["passages"].extend(x for x in now["passages"] if x["d"] == f["path"])
        alive = {f["path"] for f in work["folders"]}
        work["passages"] = [x for x in work["passages"] if x["d"] in alive]
        _store(work)


def add(cfg, path: str) -> dict:
    """Index a new folder (see check_folder for which ones may be added)."""
    folder = check_folder(cfg, path)
    if not _scan_lock.acquire(blocking=False):
        raise LibraryError("already reading a folder - try again in a moment")
    try:
        with _lock:
            work = load()
            work = {"folders": [], "passages": []} if work.get("unreadable") else _copy(work)
        key = str(folder)
        for f in work["folders"]:
            other = Path(f["path"])
            if other == folder or other in folder.parents or folder in other.parents:
                raise LibraryError(f"overlaps a folder already in the library: {other}")
        if len(work["folders"]) >= MAX_FOLDERS:
            raise LibraryError(f"at most {MAX_FOLDERS} folders")
        entry = {"path": key, "added": time.strftime("%Y-%m-%d"), "files": {}}
        work["folders"].append(entry)
        out = _scan(entry, work, cfg.allowed_roots)
        _merge(work, {key})
        return out
    finally:
        _scan_lock.release()


def remove(path: str) -> bool:
    with _lock:
        data = load()
        entry = next((f for f in data["folders"] if f["path"] == str(path)), None)
        if entry is None and path and not odd_path(str(path)):
            target = str(Path(path).expanduser().resolve())
            entry = next((f for f in data["folders"] if f["path"] == target), None)
        if not entry:
            return False
        data = _copy(data)
        data["folders"] = [f for f in data["folders"] if f["path"] != entry["path"]]
        data["passages"] = [x for x in data["passages"] if x["d"] != entry["path"]]
        _store(data)
        return True


def refresh(cfg) -> list[dict]:
    """Re-read what changed in every folder. A folder that is gone or no longer allowed loses its passages (it stays
    listed as unavailable, so the user sees why)."""
    if not _scan_lock.acquire(blocking=False):
        return [{"folder": "", "error": "already reading a folder"}]
    try:
        with _lock:
            work = _copy(load())
        out, changed = [], False
        for entry in work["folders"]:
            try:
                check_folder(cfg, entry["path"])
                r = _scan(entry, work, cfg.allowed_roots)
                changed = changed or r["changed"]
                out.append(r)
            except (LibraryError, PolicyError) as e:
                was = entry.get("unavailable")
                work["passages"] = [x for x in work["passages"] if x["d"] != entry["path"]]
                entry.update(files={}, unavailable=str(e))
                changed = changed or was != str(e)
                out.append({"folder": entry["path"], "error": str(e)})
            except Exception as e:  # one broken folder never stops the others (and never kills the thread silently)
                out.append({"folder": entry["path"], "error": f"{type(e).__name__}: {str(e)[:80]}"})
        if changed:  # rewriting the index (and rebuilding the search) only when something changed
            _merge(work, set())
        return out
    finally:
        _scan_lock.release()


def folders() -> list[dict]:
    data = load()
    count = Counter(x["d"] for x in data["passages"])
    return [{"path": f["path"], "files": len(f.get("files", {})), "passages": count.get(f["path"], 0),
             "skipped": f.get("skipped", 0), "skipped_sample": f.get("skipped_sample", []),
             "hidden": f.get("hidden", 0), "unavailable": f.get("unavailable", ""),
             "updated": f.get("updated", ""), "added": f.get("added", "")} for f in data["folders"]]


# --- search (BM25) -------------------------------------------------------------------------------------------------

def _terms(text: str) -> list[str]:
    """Words, case- and accent-folded; long words cut to a stem of 6 letters so that plain endings still match
    ("contracts" ~ "contract", "renewal" ~ "renewed") in any language."""
    text = unicodedata.normalize("NFKC", text).casefold()
    words = re.findall(r"\w+", text)
    return [w[:6] if len(w) > 6 and not w.isdigit() else w for w in words if len(w) > 1 or w.isdigit()]


def _index(data: dict):
    if _cache["index"] is not None and _cache["data"] is data:
        return _cache["index"]
    docs = [Counter(_terms(x["f"].replace("/", " ") + " " + x["t"])) for x in data["passages"]]
    df = Counter()
    for d in docs:
        df.update(d.keys())
    lens = [sum(d.values()) for d in docs]
    avg = (sum(lens) / len(lens)) if lens else 1.0
    _cache["index"] = (docs, df, lens, avg)
    return _cache["index"]


def _usable(data: dict, roots: list[str] | None) -> set[str]:
    """Folders that may be searched now: still listed, still there and - when ROOTS is given - still allowed."""
    ok = set()
    for f in data["folders"]:
        if f.get("unavailable") or not Path(f["path"]).is_dir():
            continue
        if roots is not None:
            try:
                resolve_path(f["path"], roots)
            except PolicyError:
                continue
        ok.add(f["path"])
    return ok


def search(question: str, folder: str = "", k: int = TOP, roots: list[str] | None = None) -> list[dict]:
    """The best passages for QUESTION: [{"file", "folder", "part", "text", "score"}], best first."""
    with _lock:
        data = load()
        docs, df, lens, avg = _index(data)
        usable = _usable(data, roots)
    q = [t for t in dict.fromkeys(_terms(question))]
    if not q or not docs:
        return []
    n = len(docs)
    k1, b = 1.4, 0.75
    if folder:  # given by the model: matched as text (full path or the folder's name) - never opened or resolved
        f = str(folder).strip().rstrip("\\/").casefold()
        usable = {d for d in usable if d.casefold() == f or Path(d).name.casefold() == f}
    scored = []
    for i, d in enumerate(docs):
        x = data["passages"][i]
        if x["d"] not in usable:
            continue
        s = 0.0
        for t in q:
            tf = d.get(t)
            if tf:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * lens[i] / avg))
        if s > 0:
            scored.append((s, i))
    scored.sort(reverse=True)
    floor = scored[0][0] * 0.35 if scored else 0  # far weaker matches (only "the", "is" ...) only add noise
    out, per_file = [], Counter()
    for s, i in scored:
        if s < floor:
            break
        x = data["passages"][i]
        if per_file[(x["d"], x["f"])] >= 2:  # at most two passages from one file: more files, better answers
            continue
        per_file[(x["d"], x["f"])] += 1
        out.append({"file": x["f"], "folder": x["d"], "part": x["n"] + 1, "text": x["t"], "score": round(s, 2)})
        if len(out) >= k:
            break
    return out
