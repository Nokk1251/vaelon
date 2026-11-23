"""Web tools. Everything fetched is untrusted: SSRF-guarded, size-capped, fenced as data."""
from __future__ import annotations

import re
import shutil
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import requests

from .. import config, guardian
from ..security import ssrf
from ..security.injection import fence
from ..security.policy import Risk, resolve_path
from .registry import tool

UA = {"User-Agent": "Vaelon/0.1 (+local agent)"}
MAX_BYTES = 2_000_000


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.parts.append(data.strip())


def _guard(url: str) -> None:
    """SSRF guard + Guardian link check on every hop; obviously malicious links are never opened."""
    ssrf.check_url(url)
    from ..security import dlp

    if dlp.find(url):
        raise ValueError("blocked: this address contains one of your stored secrets")
    score, reasons = guardian.url_risk(url)
    if score >= 3:
        raise ValueError("Guardian blocked a dangerous-looking link: " + "; ".join(reasons))


def _get(url: str, stream=False):
    _guard(url)
    r = requests.get(url, headers=UA, timeout=20, stream=stream, allow_redirects=False)
    hops = 0
    while r.is_redirect and hops < 5:  # re-validate every redirect hop
        url = requests.compat.urljoin(url, r.headers["location"])
        _guard(url)
        r = requests.get(url, headers=UA, timeout=20, stream=stream, allow_redirects=False)
        hops += 1
    r.raise_for_status()
    return r


def cutter(r):
    """What stops a response that hangs inside one read. r.close() from another thread waits until the hanging read is
    over (it needs the lock the reading thread holds); shutting the socket down (urllib3 >= 2.3) ends the read at once."""
    def cut():
        try:
            r.raw.shutdown()
        except Exception:  # no shutdown (older urllib3), already closed, or back in the pool
            try:
                r.close()
            except Exception:
                pass
    return cut


def _capped(r, cap: int, seconds: float = 45.0, grace: float = 5.0) -> bytes:
    """At most `cap` bytes (after decompression), and never longer than `seconds` in total (a server that drips one
    byte every few seconds, or an endless / compressed-bomb page, cannot hold a task)."""
    import time

    import threading

    end, buf = time.monotonic() + seconds, bytearray()
    watchdog = threading.Timer(seconds + grace, cutter(r))  # a read that hangs inside one chunk is cut too
    watchdog.daemon = True
    watchdog.start()
    try:
        for chunk in r.iter_content(65536):
            buf += chunk
            if len(buf) >= cap or time.monotonic() > end:
                break
    except Exception:
        if not buf:
            raise
    finally:
        watchdog.cancel()
        r.close()
    return bytes(buf[:cap])


def fetch_page(url: str) -> tuple[str, list[str]]:
    """(readable text, Guardian warnings). The raw HTML (scripts included) is scanned before stripping."""
    r = _get(url, stream=True)
    body = _capped(r, MAX_BYTES).decode(r.encoding or "utf-8", errors="replace")
    warnings = guardian.content_risk(body) + guardian.url_risk(r.url or url)[1]
    if "html" in r.headers.get("content-type", ""):
        p = _Text()
        p.feed(body)
        body = " ".join(p.parts)
    return re.sub(r"\s+", " ", body).strip(), warnings


def fetch_text(url: str) -> str:
    """Raw readable text of a public page (SSRF-guarded, size-capped). NOT fenced - callers must treat it as untrusted."""
    return fetch_page(url)[0]


def search_results(query: str, limit: int = 6, region: str = "") -> list[dict]:
    """[{title, href, body, date}] from the best search source that answers (see vaelon/search.py).
    `region` (us-en, bg-bg ...) keeps results in the user's language."""
    from .. import search

    return search.search(query, limit, region[-2:] if region else "")[0]


@tool("web_fetch", "Fetch a public web page as plain text (untrusted data)", {"url": "http(s) URL"},
      untrusted=True, group="web")
def web_fetch(ctx, url):
    text, warnings = fetch_page(url)
    head = ("GUARDIAN WARNINGS: " + "; ".join(warnings) + "\n") if warnings else ""
    return head + fence(text, url)[0]


@tool("web_search", "Search the web. Returns titles, links, snippets (untrusted)",
      {"query": "search terms"}, untrusted=True, group="web")
def web_search(ctx, query):
    from .. import search

    rows, source = search.search(str(query), 6, ctx.extra.get("lang") or "")
    if not rows:
        # say what happened: "no results" would make the model conclude that nothing exists
        return ("ERROR: no search engine answered just now (public engines throttle automatic requests). "
                "Try once more in a minute, open a site you know with web_fetch, or tell the user that the search "
                "is unavailable - do not answer from memory as if you had searched.")
    txt = "\n".join(f"{x['title']} - {x['href']}{' (' + x['date'] + ')' if x.get('date') else ''}\n  {x['body']}" for x in rows)
    return fence(txt, f"web_search via {source}")[0]


@tool("download_file", "Download a public URL into the downloads folder", {"url": "http(s) URL", "?filename": "name"},
      risk=Risk.DANGEROUS, group="web",
      summary=lambda a: f"DOWNLOAD {a.get('url')}" + (f" AS {a.get('filename')}" if a.get("filename") else ""))
def download_file(ctx, url, filename=""):
    import time

    from .create import _safe_name

    dl = Path(ctx.cfg.allowed_roots[0]).expanduser() / "Downloads"
    dl.mkdir(parents=True, exist_ok=True)
    raw = Path(str(filename) or Path(urlparse(url).path).name or "download.bin").name
    stem, ext = _safe_name(Path(raw).stem, "download"), "".join(c for c in Path(raw).suffix if c.isalnum() or c == ".")[:10]
    dest, n = dl / f"{stem}{ext}", 2
    while dest.exists():  # never overwrite a file already in Downloads
        dest, n = dl / f"{stem} ({n}){ext}", n + 1
    dest = resolve_path(str(dest), ctx.cfg.allowed_roots)
    r = _get(url, stream=True)
    import threading

    watchdog = threading.Timer(610, cutter(r))  # never longer than about 10 minutes, even inside one slow read
    watchdog.daemon = True
    watchdog.start()
    size, end = 0, time.monotonic() + 600
    with dest.open("wb") as f:
        for chunk in r.iter_content(65536):
            if time.monotonic() > end:
                f.close()
                dest.unlink(missing_ok=True)
                raise ValueError("the download took longer than 10 minutes")
            size += len(chunk)
            if size > 200_000_000:
                f.close()
                dest.unlink(missing_ok=True)
                raise ValueError("file larger than 200 MB limit")
            f.write(chunk)
    guardian.mark_from_internet(dest)  # Protected View / SmartScreen / Gatekeeper, as for a browser download
    clean, detail = guardian.scan_path(dest)  # every download is scanned automatically
    if clean is False:
        q = config.HOME / "quarantine"
        q.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dest), str(q / dest.name))
        return f"THREAT FOUND - the file was quarantined in {q} and NOT kept in Downloads.\n{detail}"
    note = "virus scan: clean" if clean else f"virus scan not available ({detail})"
    return f"saved {dest} ({size} bytes); {note}. Not executed."
