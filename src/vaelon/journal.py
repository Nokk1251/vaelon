"""The journal of a workspace: who changed what and when - bills, invoices, budget, deals, people, sign-ins.

Append-only, one line per entry. Each line is ENCRYPTED (vault) and carries an HMAC over the entry and the previous
line's HMAC (the key comes from the vault): a line edited, removed or inserted outside Vaelon breaks the chain and
`verify()` says where. Vaelon itself never offers to edit or delete it. Written only while company mode is on.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from pathlib import Path

from .security import vault

FILE = "journal.log"
GENESIS = "0" * 64
_lock = threading.Lock()


def _path(ws_dir: Path | None = None) -> Path:
    from . import company

    return (ws_dir or company.data_dir()) / FILE


def _mac(entry: dict, prev: str) -> str:
    body = json.dumps(entry, sort_keys=True, ensure_ascii=False).encode() + prev.encode()
    return hmac.new(vault.subkey("journal"), body, hashlib.sha256).hexdigest()


def _last_mac(p: Path) -> str:
    if not p.exists():
        return GENESIS
    lines = [ln for ln in p.read_text("utf-8").splitlines() if ln.strip()]
    if not lines:
        return GENESIS
    try:
        return json.loads(vault.decrypt_text(lines[-1]))["mac"]
    except Exception:
        return "broken"


def add(action: str, detail: str = "", who: str | None = None, admin: bool = False) -> None:
    """Record one action (company mode only). Never raises into the caller's work. `admin`: sign-ins, people,
    companies - they go to ONE journal (the personal folder's), not to whichever company happens to be open."""
    from . import company, config

    try:
        if not company.enabled():
            return
        u = company.user()
        name = who or ("Vaelon" if getattr(company._local, "system", False) else (u["name"] if u else "?"))
        role = "" if who else (u["role"] if u else "")
        entry = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "who": name, "role": role, "action": str(action)[:60],
                 "detail": str(detail)[:300], "ws": company.workspace()}
        with _lock:
            p = _path(config.HOME if admin else None)
            prev = _last_mac(p)
            mac = _mac(entry, prev)
            line = vault.encrypt_text(json.dumps({**entry, "prev": prev, "mac": mac}, ensure_ascii=False))
            with p.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            _anchor(p.parent, mac)
    except Exception:
        pass  # the journal must never break the work it records


def _anchor(folder: Path, mac: str) -> None:
    """Remember how many entries a journal has and its last mac (in company.enc): cutting lines off the END, putting
    an older copy back or deleting the file then shows (the chain alone cannot see that)."""
    from . import company

    def go(data):
        n = data["anchors"].get(str(folder), [0, ""])[0] + 1
        data["anchors"][str(folder)] = [n, mac]
    company._change(go)


def read(limit: int = 500, ws_dir: Path | None = None) -> list[dict]:
    """The newest entries first (without the chain fields)."""
    p = _path(ws_dir)
    if not p.exists():
        return []
    out = []
    for ln in p.read_text("utf-8").splitlines():
        if not ln.strip():
            continue
        try:
            e = json.loads(vault.decrypt_text(ln))
            out.append({k: e[k] for k in ("t", "who", "role", "action", "detail", "ws") if k in e})
        except Exception:
            out.append({"t": "", "who": "", "role": "", "action": "unreadable line", "detail": "", "ws": ""})
    return list(reversed(out))[:limit]


def verify(ws_dir: Path | None = None) -> tuple[bool, str]:
    """(ok, what): checks every line's HMAC and the chain between them."""
    from . import company

    p = _path(ws_dir)
    anchor = company.load().get("anchors", {}).get(str(p.parent))
    if not p.exists():
        return (False, "the journal file is missing") if anchor else (True, "empty")
    prev = GENESIS
    n = 0
    for n, ln in enumerate((x for x in p.read_text("utf-8").splitlines() if x.strip()), 1):
        try:
            e = json.loads(vault.decrypt_text(ln))
        except Exception:
            return False, f"line {n} cannot be read"
        entry = {k: v for k, v in e.items() if k not in ("prev", "mac")}
        if e.get("prev") != prev:
            return False, f"line {n}: the chain is broken (a line before it was removed or inserted)"
        if not hmac.compare_digest(e.get("mac", ""), _mac(entry, prev)):
            return False, f"line {n} was changed"
        prev = e["mac"]
    if anchor and (n != anchor[0] or prev != anchor[1]):
        return False, (f"{anchor[0] - n} entries at the end are missing" if n < anchor[0] else
                       "the journal is not the one Vaelon last wrote (an older or other copy)")
    return True, f"{n} entries, chain intact"


def rows_for_export() -> list[list]:
    rows = [["Time", "Who", "Role", "Action", "Detail"]]
    for e in reversed(read(100000)):
        rows.append([e["t"], e["who"], e["role"], e["action"], e["detail"]])
    return rows
