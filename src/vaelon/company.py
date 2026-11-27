"""Company mode: several workspaces (companies) with their own money data, people with roles and a PIN, and a
journal of who changed what (journal.py).

OFF by default - then Vaelon is the owner's personal assistant exactly as before. Turning it on makes the owner the
first user (with a PIN); the owner adds companies and people. What each role may do:

    owner       everything, including people, companies, the personal workspace and the journal
    accountant  bills, invoices, budget, bank import, export, business details, journal; reads deals
    sales       deals; reads invoices
    member      records expenses and income; reads bills
    viewer      reads bills, invoices, budget and deals - changes nothing

Money data (bills, invoices, business details, budget, deals, the journal) lives per workspace:
the personal workspace keeps today's files in ~/.vaelon, a company gets ~/.vaelon/workspaces/<id>/. The calendar,
contacts, memory and conversations stay personal.

HONEST LIMIT: on ONE Windows account this protects against mistakes and casual misuse, not against a person who
can use that Windows account directly (the data is sealed with that account's key). For real separation give each
person their own Windows account - or, later, a shared server (not built: the API listens only on this PC).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import time
import uuid
from pathlib import Path

from . import config
from .security import vault

FILE = "company.enc"
PERSONAL = "personal"
ALL = "*"
PERMS = ("bills.read", "bills.write", "invoices.read", "invoices.write", "budget.read", "budget.write", "budget.limits",
         "deals.read", "deals.write", "quotes.read", "quotes.write", "profile.write", "export", "bank.import",
         "journal.read", "users.manage", "workspaces.manage", "integrations")
ROLES = {
    "owner": set(PERMS),
    "accountant": {"bills.read", "bills.write", "invoices.read", "invoices.write", "budget.read", "budget.write",
                   "budget.limits", "deals.read", "quotes.read", "quotes.write", "profile.write", "export", "bank.import",
                   "journal.read", "integrations"},
    "sales": {"deals.read", "deals.write", "invoices.read", "quotes.read", "quotes.write"},
    "member": {"budget.read", "budget.write", "bills.read"},
    "viewer": {"bills.read", "invoices.read", "budget.read", "deals.read", "quotes.read"},
}
ROLE_NAMES = tuple(ROLES)
PIN_RX = re.compile(r"^\d{4,8}$")
MAX_TRIES, LOCK_SECONDS = 5, 60
_lock = threading.RLock()
_local = threading.local()
# the app's session (one desktop app = one person at the keyboard at a time)
_session = {"user": None, "workspace": PERSONAL}
_fails: dict[str, list[float]] = {}


class Denied(PermissionError):
    """Not allowed for this role (or nobody is signed in)."""


# ---------------------------------------------------------------- storage

def _path() -> Path:
    return config.HOME / FILE


def _empty() -> dict:
    return {"enabled": False, "workspaces": [{"id": PERSONAL, "name": "Personal", "created": time.strftime("%Y-%m-%d")}],
            "users": [], "lock_on_start": False, "last_workspace": PERSONAL,
            "fails": {},     # wrong PINs per person: [count, locked until]
            "anchors": {}}   # per journal folder: [entries, last mac] - so a cut-off end of a journal is noticed


def _locked_shut() -> dict:
    """company.enc exists but cannot be read (locked by an antivirus scan, damaged, wrong key): company mode stays ON
    and nobody is signed in - failing OPEN would hand the owner's personal parts to whoever is at the keyboard."""
    data = _empty()
    data["enabled"], data["unreadable"] = True, True
    return data


def load(strict: bool = False) -> dict:
    p = _path()
    if not p.exists():
        return _empty()
    data = None
    for attempt in range(3):  # a moment's sharing violation (another thread replacing the file) is retried
        try:
            data = json.loads(vault.decrypt_text(p.read_text("utf-8").strip()))
            break
        except Exception:
            if attempt < 2:
                time.sleep(0.05)
    if data is None:
        if strict:
            raise RuntimeError(f"{FILE} could not be read, so nothing was changed")
        return _locked_shut()
    base = _empty()
    base.update({k: v for k, v in data.items() if k in base})
    return base


def _store(data: dict) -> None:
    config.HOME.mkdir(parents=True, exist_ok=True)
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(vault.encrypt_text(json.dumps({k: v for k, v in data.items() if k != "unreadable"},
                                                  ensure_ascii=False)), "utf-8")
    for attempt in range(5):  # Windows: replace fails while another thread is reading the file
        try:
            tmp.replace(_path())
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def _change(fn):
    with _lock:
        data = load(strict=True)
        out = fn(data)
        _store(data)
        return out


# ---------------------------------------------------------------- who is acting

def enabled() -> bool:
    return bool(load().get("enabled"))


def system(on: bool = True) -> None:
    """Mark THIS thread as Vaelon itself (the reminder thread writing 'already announced'): no role checks."""
    _local.system = on


def bind(uid: str | None, ws: str) -> None:
    """Freeze who and where for THIS thread (a task's thread): a sign-in or a switch of company while the task runs
    must not change whose rights it uses or which company's files it writes (found by the code review)."""
    _local.bound = (uid, ws)


def unbind() -> None:
    _local.bound = None


def bound() -> tuple | None:
    """What THIS thread is bound to (handed on to helper threads a task starts)."""
    return getattr(_local, "bound", None)


def owner_id() -> str | None:
    return next((u["id"] for u in load()["users"] if u["role"] == "owner"), None)


def user() -> dict | None:
    """The signed-in person (None = nobody / locked). With company mode off: the owner, always."""
    if not enabled():
        return {"id": "owner", "name": "Owner", "role": "owner", "workspaces": [ALL]}
    bound = getattr(_local, "bound", None)
    uid = bound[0] if bound else _session["user"]
    data = load()
    if data.get("unreadable"):
        return None
    return next((u for u in data["users"] if u["id"] == uid), None) if uid else None


def workspace() -> str:
    if not enabled():
        return PERSONAL
    bound = getattr(_local, "bound", None)
    return bound[1] if bound else _session["workspace"]


def key() -> tuple[str, str]:
    """(who, which company) - what an undo entry belongs to."""
    u = user()
    return (u["id"] if u else "", workspace())


def workspace_name(ws: str | None = None) -> str:
    ws = ws or workspace()
    w = next((x for x in load()["workspaces"] if x["id"] == ws), None)
    return w["name"] if w else ws


def data_dir() -> Path:
    """Where the money files of the current workspace live (the personal one: ~/.vaelon itself, as always).
    The reminder thread visits every workspace with `use_dir`."""
    if getattr(_local, "dir", None):
        return _local.dir
    ws = workspace()
    if ws == PERSONAL:
        return config.HOME
    d = config.HOME / "workspaces" / ws
    d.mkdir(parents=True, exist_ok=True)
    return d


class use_dir:
    """`with use_dir(path):` this thread reads and writes that workspace's files (the reminder thread)."""

    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        self.old, _local.dir = getattr(_local, "dir", None), self.path
        return self.path

    def __exit__(self, *exc):
        _local.dir = self.old
        return False


def all_dirs() -> list[Path]:
    """The folder of every workspace (the personal one first)."""
    out = [config.HOME]
    if enabled():
        for w in load()["workspaces"]:
            if w["id"] != PERSONAL:
                d = config.HOME / "workspaces" / w["id"]
                if d.is_dir():
                    out.append(d)
    return out


def guarded(fn, perm: str, action: str, describe=None):
    """Wrap a data function: check the role's permission first, journal the action after it succeeded."""
    import functools

    @functools.wraps(fn)
    def wrapper(*a, **k):
        require(perm)
        out = fn(*a, **k)
        if enabled() and not getattr(_local, "system", False):
            from . import journal

            try:
                detail = describe(out, a, k) if describe else ""
            except Exception:
                detail = ""
            journal.add(action, detail or "")
        return out

    return wrapper


def can(perm: str) -> bool:
    if getattr(_local, "system", False) or not enabled():
        return True
    u = user()
    return bool(u) and perm in ROLES.get(u["role"], set()) and _may_enter(u, workspace())


def require(perm: str) -> None:
    if can(perm):
        return
    if not user():
        raise Denied("Vaelon is locked - sign in first")
    raise Denied(f"your role ({user()['role']}) may not do this ({perm})")


_epoch = [0]  # changes on every sign-in / sign-out / switch: long-lived connections (Live) notice and close


def _bump() -> None:
    _epoch[0] += 1


def epoch() -> int:
    return _epoch[0]


def _may_enter(u: dict, ws: str) -> bool:
    if ws == PERSONAL:
        return u["role"] == "owner"  # the owner's personal money is the owner's
    return ALL in u.get("workspaces", []) or ws in u.get("workspaces", [])


# ---------------------------------------------------------------- PINs

def _hash(pin: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 200_000).hex()


def _pin_fields(pin: str) -> dict:
    if not PIN_RX.match(str(pin)):
        raise ValueError("the PIN must be 4 to 8 digits")
    salt = secrets.token_hex(16)
    return {"salt": salt, "pin": _hash(str(pin), salt)}


def check_pin(uid: str, pin: str) -> dict:
    """The ONE place a PIN is checked (sign-in, turning company mode off). Under a lock, the try is counted BEFORE the
    slow hash, and the wait grows: 5 wrong -> 1 min, then 2, 4, 8 ... up to 1 hour; kept in company.enc so a restart
    does not reset it (the review found 40 parallel tries and an unlimited `disable`)."""
    with _lock:  # the SAME lock as every other change of company.enc (a journal anchor written meanwhile is kept)
        data = load(strict=True)
        u = next((x for x in data["users"] if x["id"] == uid), None)
        key = uid if u else "?"  # tries for made-up ids are counted together (the file cannot be bloated)
        rec = data.setdefault("fails", {}).get(key, [0, 0.0])
        now = time.time()
        if now < rec[1]:
            raise Denied(f"too many wrong PINs - wait {int(rec[1] - now) + 1} s")
        ok = bool(u) and hmac.compare_digest(_hash(str(pin), u["salt"]).encode(), str(u["pin"]).encode())
        if ok:
            data["fails"].pop(key, None)
        else:
            n = rec[0] + 1
            until = now + min(3600, LOCK_SECONDS * 2 ** (n - MAX_TRIES)) if n >= MAX_TRIES else 0.0
            data["fails"][key] = [n, until]
        _store(data)
    if not ok:
        from . import journal

        journal.add("wrong PIN", u["name"] if u else "?", who="?", admin=True)
        raise Denied("wrong user or PIN")
    return u


def sign_in(uid: str, pin: str) -> dict:
    """Check a PIN and start the session."""
    u = check_pin(uid, pin)
    ws = load()["last_workspace"]
    ws = ws if _may_enter(u, ws) else next((w["id"] for w in workspaces() if _may_enter(u, w["id"])), None)
    if ws is None:  # someone with no company left must never land in the owner's personal space
        raise Denied("you have no company to work in - ask the owner")
    _session["user"], _session["workspace"] = uid, ws
    _bump()
    from . import journal

    journal.add("signed in", u["name"], admin=True)
    return public(u)


def sign_out() -> None:
    if _session["user"]:
        from . import journal

        journal.add("signed out", (user() or {}).get("name", ""), admin=True)
    _session["user"] = None
    _bump()


def start_session() -> None:
    """When the app starts: the owner is signed in (it is the owner's PC) unless 'lock on start' is set."""
    data = load()
    if not data["enabled"]:
        return
    owner = next((u for u in data["users"] if u["role"] == "owner"), None)
    _session["user"] = None if data.get("lock_on_start") or not owner else owner["id"]
    _session["workspace"] = data["last_workspace"] if owner else PERSONAL


# ---------------------------------------------------------------- turning it on, people, companies

def public(u: dict) -> dict:
    return {k: u[k] for k in ("id", "name", "role", "workspaces")}


def enable(owner_name: str, pin: str) -> dict:
    """Company mode on: the owner becomes the first user."""
    name = re.sub(r"\s+", " ", str(owner_name)).strip()[:60] or "Owner"
    fields = _pin_fields(pin)

    def go(data):
        if data["enabled"]:
            raise ValueError("company mode is already on")
        data["enabled"] = True
        owner = next((u for u in data["users"] if u["role"] == "owner"), None)
        if owner is None:
            data["users"].append({"id": uuid.uuid4().hex[:8], "name": name, "role": "owner", "workspaces": [ALL], **fields})
        else:
            owner.update(fields)  # turned on again: the PIN typed now is the owner's PIN (the old one is gone)
            data.get("fails", {}).pop(owner["id"], None)
        return next(u for u in data["users"] if u["role"] == "owner")

    owner = _change(go)
    _session["user"], _session["workspace"] = owner["id"], PERSONAL
    from . import journal

    journal.add("company mode on", name, admin=True)
    return public(owner)


def disable(pin: str) -> None:
    """Back to the personal assistant (the owner's PIN is required). People and companies are kept for later."""
    owner = next((u for u in load()["users"] if u["role"] == "owner"), None)
    if not owner:
        raise Denied("the owner's PIN is required")
    check_pin(owner["id"], pin)  # counted and slowed down like a sign-in
    from . import journal

    journal.add("company mode off", owner["name"], admin=True)

    def go(data):
        data["enabled"] = False
    _change(go)
    _session["user"], _session["workspace"] = None, PERSONAL


def add_user(name: str, role: str, pin: str, workspaces_: list[str]) -> dict:
    require("users.manage")
    if role not in ROLES:
        raise ValueError("role must be one of " + ", ".join(ROLE_NAMES))
    name = re.sub(r"\s+", " ", str(name)).strip()[:60]
    if not name:
        raise ValueError("the person needs a name")
    known = {w["id"] for w in load()["workspaces"]}
    wss = [w for w in workspaces_ if w in known and w != PERSONAL] or []
    if role != "owner" and not wss:
        raise ValueError("choose at least one company for this person")
    u = {"id": uuid.uuid4().hex[:8], "name": name, "role": role, "workspaces": [ALL] if role == "owner" else wss,
         **_pin_fields(pin)}

    def go(data):
        if any(x["name"].lower() == name.lower() for x in data["users"]):
            raise ValueError("there is already a person with that name")
        data["users"].append(u)
    _change(go)
    from . import journal

    journal.add("person added", f"{name} ({role})", admin=True)
    return public(u)


def update_user(uid: str, role: str | None = None, pin: str | None = None, workspaces_: list[str] | None = None) -> dict:
    require("users.manage")

    def go(data):
        u = next((x for x in data["users"] if x["id"] == uid), None)
        if not u:
            raise ValueError("no such person")
        owners = [x for x in data["users"] if x["role"] == "owner"]
        if role and role != u["role"]:
            if role not in ROLES:
                raise ValueError("role must be one of " + ", ".join(ROLE_NAMES))
            if u["role"] == "owner" and len(owners) == 1:
                raise ValueError("the last owner cannot change role")
            u["role"] = role
            if role == "owner":
                u["workspaces"] = [ALL]
        if pin:
            u.update(_pin_fields(pin))
        if workspaces_ is not None and u["role"] != "owner":
            known = {w["id"] for w in data["workspaces"]}
            chosen = [w for w in workspaces_ if w in known and w != PERSONAL]
            if not chosen:  # with none, a sign-in would land in the owner's personal space (review 2026-11-16)
                raise ValueError("pick at least one company (or remove the person)")
            u["workspaces"] = chosen
        return dict(u)
    u = _change(go)
    from . import journal

    journal.add("person changed", f"{u['name']} ({u['role']})" + (", new PIN" if pin else ""), admin=True)
    return public(u)


def remove_user(uid: str) -> None:
    require("users.manage")

    def go(data):
        u = next((x for x in data["users"] if x["id"] == uid), None)
        if not u:
            raise ValueError("no such person")
        if u["role"] == "owner" and sum(1 for x in data["users"] if x["role"] == "owner") == 1:
            raise ValueError("the last owner cannot be removed")
        data["users"].remove(u)
        return u
    u = _change(go)
    if _session["user"] == uid:
        _session["user"] = None
    _bump()
    from . import journal

    journal.add("person removed", u["name"], admin=True)


def users() -> list[dict]:
    return [public(u) for u in load()["users"]]


def workspaces() -> list[dict]:
    return list(load()["workspaces"])


def add_workspace(name: str) -> dict:
    require("workspaces.manage")
    name = re.sub(r"\s+", " ", str(name)).strip()[:80]
    if not name:
        raise ValueError("the company needs a name")
    ws = {"id": uuid.uuid4().hex[:8], "name": name, "created": time.strftime("%Y-%m-%d")}

    def go(data):
        if any(w["name"].lower() == name.lower() for w in data["workspaces"]):
            raise ValueError("there is already a company with that name")
        data["workspaces"].append(ws)
    _change(go)
    from . import journal

    journal.add("company added", name, admin=True)
    return ws


def rename_workspace(wid: str, name: str) -> None:
    require("workspaces.manage")
    name = re.sub(r"\s+", " ", str(name)).strip()[:80]
    if not name:
        raise ValueError("the company needs a name")

    def go(data):
        w = next((x for x in data["workspaces"] if x["id"] == wid), None)
        if not w:
            raise ValueError("no such company")
        w["name"] = name
    _change(go)


def switch(wid: str) -> dict:
    """Open another workspace (only one this person may enter)."""
    u = user()
    data = load()
    w = next((x for x in data["workspaces"] if x["id"] == wid), None)
    if not w:
        raise ValueError("no such company")
    if enabled() and (not u or not _may_enter(u, wid)):
        raise Denied("you have no access to that company")
    _session["workspace"] = wid
    _bump()

    def go(d):
        d["last_workspace"] = wid
    _change(go)
    from . import journal

    journal.add("opened", w["name"], admin=True)
    return w


def set_lock_on_start(on: bool) -> None:
    require("users.manage")

    def go(d):
        d["lock_on_start"] = bool(on)
    _change(go)


def state() -> dict:
    """What the app shows: on/off, who, which company, which companies this person may open, what the role allows."""
    data = load()
    u = user()
    ws_all = data["workspaces"]
    mine = [w for w in ws_all if (not data["enabled"]) or (u and _may_enter(u, w["id"]))]
    cur = next((w for w in ws_all if w["id"] == workspace()), ws_all[0])
    return {"enabled": data["enabled"], "user": public(u) if (u and data["enabled"]) else None,
            "locked": data["enabled"] and not u, "workspace": cur, "workspaces": mine,
            "perms": sorted(ROLES[u["role"]]) if u else [], "roles": list(ROLE_NAMES),
            "people": [{"id": x["id"], "name": x["name"]} for x in data["users"]] if data["enabled"] else [],
            "lock_on_start": data["lock_on_start"]}
