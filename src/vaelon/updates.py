"""Update check: asks the project's public GitHub Releases page whether a newer version exists.

Nothing is downloaded or installed automatically, and nothing about you is sent - it is one anonymous GET of a
public page. The check is off until the project has a public repository (`__source__` in vaelon/__init__.py, or
`vaelon config update_repo owner/name`). Always compare the SHA-256 of a download with the one on the release page.
"""
from __future__ import annotations

import re

from . import __source__, __version__, config

API = "https://api.github.com/repos/{repo}/releases/latest"


def _repo() -> str:
    cfg = config.Config.load()
    raw = getattr(cfg, "update_repo", "") or __source__
    m = re.search(r"(?:github\.com/)?([\w.-]+/[\w.-]+?)(?:\.git)?/?$", raw or "")
    return m.group(1) if m else ""


def _tuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


def newer(latest: str, current: str = __version__) -> bool:
    return _tuple(latest) > _tuple(current)


def check(timeout: float = 6.0) -> dict:
    """{"enabled", "current", "latest", "newer", "url", "notes"} - never raises."""
    repo = _repo()
    out = {"enabled": bool(repo), "current": __version__, "latest": "", "newer": False, "url": "", "notes": ""}
    if not repo:
        return out
    try:
        import requests

        r = requests.get(API.format(repo=repo), timeout=timeout, allow_redirects=False,
                         headers={"Accept": "application/vnd.github+json", "User-Agent": "vaelon-update-check"})
        r.raise_for_status()
        if r.is_redirect or r.status_code != 200:
            raise RuntimeError(f"the repository answered HTTP {r.status_code} (moved?)")
        j = r.json()
        out["latest"] = str(j.get("tag_name") or "").lstrip("v")
        out["url"] = str(j.get("html_url") or "")
        out["notes"] = str(j.get("body") or "")[:600]
        out["newer"] = newer(out["latest"])
    except Exception as e:
        out["error"] = str(e)[:160]
    return out


def report() -> str:
    c = check()
    if not c["enabled"]:
        return (f"Vaelon {c['current']}. Update checks are off: the project has no public repository yet "
                "(set one with: vaelon config update_repo owner/name).")
    if c.get("error"):
        return f"Vaelon {c['current']}. Could not check for updates: {c['error']}"
    if c["newer"]:
        return (f"Vaelon {c['latest']} is available (you have {c['current']}): {c['url']}\n"
                "Download it from that page only, and compare the file's SHA-256 with the one listed there.")
    return f"Vaelon {c['current']} is the newest version."
