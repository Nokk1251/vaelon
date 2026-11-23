"""Update check: is there a newer Vaelon? OFF unless the user turns it on (Settings > Updates) or asks once (the
"Check now" button, `vaelon update`).

What it does: one HTTPS GET of a fixed address - the public "latest release" of Vaelon's own GitHub repository
(`__source__`). No cookies, no ID, no stored login (.netrc is never read), nothing about the user or this computer in
the request; GitHub sees the IP address, as any website does. At most once a day while it is on - also across restarts
(the time and the answer are kept in update_check.json in Vaelon's data folder: a version number, nothing personal) -
and "Check now" / `vaelon update` at most once a minute.

What it never does: download, install or run anything; follow a link or a redirect from the answer; show the release
text or give it to the model. From the answer it keeps ONE thing - the version number, accepted only in the form
1.2.3 (ASCII digits) - and builds the link to the download page itself (always the project's own Releases page).

A slow or stuck answer can never hold the app: the request runs on ONE worker thread and callers wait a few seconds
at most. Once GitHub's headers have arrived, the answer is cut after 2 x timeout (the socket is shut down, which also
ends a read that hangs inside one chunk). A server that drips its HEADERS byte by byte can keep that one thread waiting
longer (each read has its own timeout); meanwhile every check answers "still checking" and no second thread starts.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

from . import __source__, __version__

API = "https://api.github.com/repos/{repo}/releases/latest"
PAGE = "https://github.com/{repo}/releases/tag/v{version}"
SOURCE_RX = re.compile(r"https://github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9._-]{1,100})")
TAG_RX = re.compile(r"v?([0-9]{1,4})\.([0-9]{1,4})\.([0-9]{1,4})")  # ASCII digits only
MAX_BYTES = 256 * 1024  # a release answer is a few KB; anything bigger is not read
DAY = 24 * 3600
RETRY = 3600  # after a failed check, wait an hour before asking again
FORCE_GAP = 60  # "Check now" pressed again within a minute gets the last answer (GitHub allows 60 an hour per IP)

_lock = threading.Lock()  # guards the state below - never held while the network is used
_last: dict = {"t": 0.0, "result": None}
_busy: dict = {"thread": None, "done": None}


def _file() -> Path:
    from . import config

    return config.HOME / "update_check.json"


def _load() -> None:
    """The last answer kept on disk (so a restart does not ask again). Only well-formed values are taken."""
    if _last["result"] is not None:
        return
    try:
        raw = json.loads(_file().read_text("utf-8"))
        res, t = raw.get("result"), raw.get("t")
        latest = res.get("latest", "") if isinstance(res, dict) else None
        if isinstance(t, (int, float)) and isinstance(latest, str) and (not latest or TAG_RX.fullmatch(latest)):
            err = res.get("error")
            _last.update(t=float(t), result={
                "enabled": True, "current": __version__, "latest": latest, "newer": bool(latest) and newer(latest),
                "url": page(latest) if latest and newer(latest) else "", "checked": float(t),
                **({"error": err[:120]} if isinstance(err, str) and err else {})})
    except Exception:
        pass


def _save(out: dict) -> None:
    try:
        f = _file()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f.name + ".tmp")
        keep = {k: out[k] for k in ("latest", "error") if out.get(k)}
        tmp.write_text(json.dumps({"t": out["checked"], "result": keep}), "utf-8")
        os.replace(tmp, f)
    except Exception:
        pass


class Failed(Exception):
    """A failure whose text is Vaelon's own (safe to show)."""


def _repo() -> str:
    """owner/name of Vaelon's own repository - from the code only, never from a setting or a file."""
    m = SOURCE_RX.fullmatch(__source__.strip().removesuffix("/").removesuffix(".git"))
    return f"{m.group(1)}/{m.group(2)}" if m and m.group(2) not in (".", "..") else ""


def _tuple(v: str) -> tuple:
    m = TAG_RX.fullmatch(v.strip())
    return tuple(int(x) for x in m.groups()) if m else (0,)


def newer(latest: str, current: str = __version__) -> bool:
    return _tuple(latest) > _tuple(current)


def page(version: str) -> str:
    """The download page of a version - built here, never taken from GitHub's answer."""
    m = TAG_RX.fullmatch(version.strip())
    repo = _repo()
    return PAGE.format(repo=repo, version=".".join(str(int(x)) for x in m.groups())) if m and repo else ""


def _session():
    """A session that ignores the environment's stored logins (.netrc), CA overrides and cookies; only an HTTPS proxy the
    system names is kept, so the check still works behind one."""
    import urllib.request

    import requests

    s = requests.Session()
    s.trust_env = False
    try:
        proxy = urllib.request.getproxies().get("https")
    except Exception:
        proxy = None
    s.proxies = {"https": proxy} if proxy else {}
    return s


def _fetch(repo: str, timeout: float) -> str:
    """The newest released version number ('1.2.3'), or an exception. Never longer than 2 x timeout."""
    from .tools.web import cutter

    end = time.monotonic() + 2 * timeout
    s = _session()
    r = watchdog = None
    try:
        r = s.get(API.format(repo=repo), timeout=(timeout, timeout), allow_redirects=False, stream=True,
                  headers={"Accept": "application/vnd.github+json", "User-Agent": "vaelon-update-check",
                           "Accept-Encoding": "identity"})
        watchdog = threading.Timer(max(0.05, end - time.monotonic()), cutter(r))
        watchdog.daemon = True
        watchdog.start()
        if r.status_code != 200:
            raise Failed(f"GitHub answered HTTP {r.status_code}")
        raw = b""
        try:
            for chunk in r.iter_content(16384):
                raw += chunk
                if len(raw) > MAX_BYTES:
                    raise Failed("the answer was too large")
                if time.monotonic() > end:
                    raise Failed("the answer took too long")
        except Failed:
            raise
        except Exception:
            if time.monotonic() >= end - 0.05:
                raise Failed("the answer took too long") from None
            raise
    finally:
        if watchdog:
            watchdog.cancel()
        if r is not None:
            r.close()
        s.close()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        raise Failed("the answer was not a release") from None
    tag = data.get("tag_name") if isinstance(data, dict) else None
    m = TAG_RX.fullmatch(tag.strip()) if isinstance(tag, str) else None
    if not m:
        raise Failed("the answer held no valid version number")
    return ".".join(str(int(x)) for x in m.groups())


def _work(repo: str, timeout: float, done: threading.Event) -> None:
    import requests

    out = {"enabled": True, "current": __version__, "latest": "", "newer": False, "url": ""}
    for attempt in (1, 2):
        try:
            latest = _fetch(repo, timeout)
            out.update(latest=latest, newer=newer(latest), url=page(latest) if newer(latest) else "")
        except Failed as e:
            out["error"] = str(e)
        except requests.exceptions.SSLError:
            out["error"] = "no secure connection to GitHub - a firewall or a company network may block it"
        except requests.exceptions.ConnectionError:  # also a connect timeout: a lost first packet is common
            if attempt == 1:
                time.sleep(1)
                continue
            out["error"] = "could not connect to GitHub - check the internet connection and try again"
        except requests.exceptions.Timeout:
            out["error"] = "GitHub did not answer in time - try again later"
        except Exception as e:
            out["error"] = f"could not reach GitHub ({type(e).__name__})"
        break
    out["checked"] = time.time()
    with _lock:
        _last.update(t=out["checked"], result=out)
        _save(out)
    try:
        from .security import audit

        audit.log("update_check", result=out.get("latest") or out.get("error", ""))
    except Exception:
        pass
    done.set()


def check(timeout: float = 6.0, force: bool = False) -> dict:
    """{"enabled", "current", "latest", "newer", "url", "checked", "error"?, "checking"?} - never raises, never blocks
    longer than about 2 x timeout + 2 s. Asks GitHub at most once a day (once an hour after a failure); `force` (the
    user pressed "Check now") asks again, but not twice within a minute."""
    repo = _repo()
    out = {"enabled": bool(repo), "current": __version__, "latest": "", "newer": False, "url": "", "checked": 0.0}
    if not repo:
        return out
    with _lock:
        _load()
        last, age = _last["result"], time.time() - _last["t"]
        wait = FORCE_GAP if force else (RETRY if last and last.get("error") else DAY)
        if last and 0 <= age < wait:  # a clock set back (age < 0) counts as expired
            return dict(last)
        worker = _busy["thread"]
        if not (worker and worker.is_alive()):  # one question at a time, however many callers
            done = threading.Event()
            worker = threading.Thread(target=_work, args=(repo, timeout, done), daemon=True, name="update-check")
            _busy.update(thread=worker, done=done)
            worker.start()
        done = _busy["done"]
    if done.wait(timeout * 2 + 2):
        with _lock:
            if _last["result"]:
                return dict(_last["result"])
    return {**out, "checking": True, "error": "still checking - try again in a minute"}


def report() -> str:
    c = check(force=True)
    if not c["enabled"]:
        return f"Vaelon {c['current']}. This copy has no project address, so it cannot check for updates."
    if c.get("checking"):
        return f"Vaelon {c['current']}. GitHub is slow to answer - still checking; try again in a minute."
    if c.get("error"):
        return f"Vaelon {c['current']}. Could not check for updates: {c['error']}"
    if c["newer"]:
        return (f"Vaelon {c['latest']} is available (you have {c['current']}): {c['url']}\n"
                "Download it from that page only and run the installer over this version - your data and settings "
                "stay. Compare the file's SHA-256 with the one listed there.")
    return f"Vaelon {c['current']} is the newest version."
