"""Integrity: signed fingerprints of Vaelon's code and of every plugin/hook you approved.

- `verify()` compares SHA-256 hashes of all source files with a manifest signed by HMAC-SHA256 (key from the
  vault). If malware or a person edits Vaelon's code, the change is detected at start-up.
- Plugins and hooks run ONLY if their exact hash was approved (create_tool / `vaelon trust ...`).
  A .py file dropped into ~/.vaelon/plugins by anything else is ignored.
- Approved self-modifications re-sign the manifest automatically.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sys
from pathlib import Path

from .. import config
from . import vault

PKG = Path(__file__).resolve().parent.parent
FILE = "integrity.json"
# one manifest per installation (source checkout and packaged app can share ~/.vaelon)
ROOT_ID = hashlib.sha256(str(PKG).lower().encode()).hexdigest()[:12]
FROZEN = bool(getattr(sys, "frozen", False))  # packaged app: code lives inside the bundle


def _hash(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def code_manifest() -> dict[str, str]:
    files = {}
    for p in sorted(PKG.rglob("*")):
        if p.is_file() and p.suffix in (".py", ".md") and "__pycache__" not in p.parts and "webui" not in p.parts:
            files[p.relative_to(PKG).as_posix()] = _hash(p)
    return files


def _mac(body: dict) -> str:
    return hmac.new(vault.subkey("integrity"), json.dumps(body, sort_keys=True).encode(), hashlib.sha256).hexdigest()


def _load() -> dict:
    p = config.HOME / "secrets" / FILE
    if not p.exists():
        return {}
    data = json.loads(p.read_text("utf-8"))
    mac = data.pop("mac", "")
    if not hmac.compare_digest(mac, _mac(data)):
        return {"tampered": True}
    return data


def _save(data: dict) -> None:
    data = {k: v for k, v in data.items() if k != "tampered"}
    data["mac"] = _mac(data)
    p = config.HOME / "secrets" / FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1), "utf-8")


def sign_code() -> int:
    data = _load()
    if data.get("tampered"):
        data = {}
    if not isinstance(data.get("code"), dict) or any(isinstance(v, str) for v in data["code"].values()):
        data["code"] = {}  # older single-installation format
    manifest = code_manifest()
    data["code"][ROOT_ID] = manifest
    _save(data)
    vault.write_secret(f"integrity_signed_{ROOT_ID}", b"1")
    return len(manifest)


def verify_code() -> tuple[bool, list[str]]:
    """(ok, problems). First run: trust-on-first-use, the current code is signed."""
    if FROZEN:
        # the installed app: its code sits in the signed exe's archive; the program folder (Program Files) is protected
        # by Windows - writable only with administrator rights. No per-file check runs here (said so in the docs).
        return True, []
    data = _load()
    if data.get("tampered"):
        return False, ["the integrity manifest itself was modified (signature invalid)"]
    signed = (data.get("code") or {}).get(ROOT_ID) if isinstance(data.get("code"), dict) else None
    if not isinstance(signed, dict):
        if vault.read_secret(f"integrity_signed_{ROOT_ID}"):
            # it WAS signed before: a missing manifest is not a first start - deleting it must not reset the trust
            return False, ["the signed list of Vaelon's code files is missing (deleted?) - run: vaelon integrity sign"]
        sign_code()
        return True, []
    now = code_manifest()
    problems = [f"modified: {f}" for f in now if f in signed and now[f] != signed[f]]
    problems += [f"new file: {f}" for f in now if f not in signed]
    problems += [f"missing: {f}" for f in signed if f not in now]
    return not problems, problems


def trust(kind: str, path: Path) -> str:
    """Approve the exact current content of a plugin/hook."""
    data = _load()
    if data.get("tampered"):
        data = {}
    data.setdefault(kind, {})[path.name] = _hash(path)
    _save(data)
    return data[kind][path.name]


def is_trusted(kind: str, path: Path) -> bool:
    data = _load()
    if data.get("tampered"):
        return False
    expected = data.get(kind, {}).get(path.name)
    return bool(expected) and hmac.compare_digest(expected, _hash(path))
