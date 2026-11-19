"""Web search from the best source that answers.

    Tavily       (TAVILY_API_KEY, free plan)        official search API made for AI agents
    Brave Search (BRAVE_SEARCH_API_KEY, free plan)  official API of an independent index
    metasearch   (no key, the `ddgs` package)       asks several public engines as a browser would - they
                                                    throttle or refuse such requests without warning
    Wikipedia + DuckDuckGo instant answers (no key) official and always there, but encyclopedic only

Tried in that order; a source that fails, is throttled or finds nothing hands over to the next, and the result
says where it came from. So a search never ends in a bare error just because one engine said "no".
Results are merged, de-duplicated (two per site at most) and ordered by how well they match the question.
With a key, only the search words go to that service - never the conversation. Keys travel in a header and are
bound to their host (providers.KEY_HOSTS).
"""
from __future__ import annotations

import re
import threading
from urllib.parse import urlparse

import requests

from . import config

TAVILY, BRAVE = "https://api.tavily.com/search", "https://api.search.brave.com/res/v1/web/search"
TAVILY_KEY, BRAVE_KEY = "TAVILY_API_KEY", "BRAVE_SEARCH_API_KEY"
META_SECONDS = 9.0  # the keyless engines get this long in total
ERRORS = (requests.RequestException, KeyError, ValueError, TypeError, IndexError, AttributeError)
# words that ask for something recent -> the engines are told to look at the last day / week
DAY_RX = re.compile(r"(?i)\b(today|tonight|yesterday|right now|breaking)\b|днес|вчера|тази вечер|в момента")
WEEK_RX = re.compile(r"(?i)\b(this week|latest news|news|headlines|recent(ly)?)\b|новини|тази седмица|последните дни|наскоро")
STOP = set("the a an of in on at to for and or is are was were be what who how when where why which with from by as "
           "about it this that do does did на в във за и или е са от с със по как кой коя кое кои къде кога какво "
           "какъв да ли се то този тази това".split())


class Unavailable(Exception):
    pass


def _row(title, href, body, date="") -> dict:
    clean = lambda s: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", str(s or ""))).strip()  # noqa: E731
    return {"title": clean(title)[:160], "href": str(href or "").strip(), "body": clean(body)[:500], "date": str(date or "")[:10]}


def freshness(query: str) -> str:
    """'d', 'w' or '' - how recent the answer has to be, judged from the words of the question."""
    return "d" if DAY_RX.search(query) else "w" if WEEK_RX.search(query) else ""


# ---------------------------------------------------------------- sources

def tavily(query: str, limit: int, lang: str, fresh: str, key: str) -> list[dict]:
    from .tools.web import UA, _guard

    _guard(TAVILY)
    body = {"query": query, "max_results": limit, "search_depth": "basic"}  # basic = 1 credit, never more
    if fresh:
        body.update(time_range={"d": "day", "w": "week"}[fresh], topic="news")
    r = requests.post(TAVILY, json=body, headers={**UA, "Authorization": "Bearer " + key}, timeout=12, allow_redirects=False)
    if r.status_code != 200:
        raise Unavailable(f"HTTP {r.status_code}")
    return [_row(x.get("title"), x.get("url"), x.get("content"), x.get("published_date")) for x in r.json().get("results") or []]


def brave(query: str, limit: int, lang: str, fresh: str, key: str) -> list[dict]:
    from .tools.web import UA, _guard

    _guard(BRAVE)
    params = {"q": query, "count": limit}
    if lang in ("bg", "en"):
        params["search_lang"] = lang
    if fresh:
        params["freshness"] = {"d": "pd", "w": "pw"}[fresh]
    r = requests.get(BRAVE, params=params, headers={**UA, "X-Subscription-Token": key, "Accept": "application/json"},
                     timeout=12, allow_redirects=False)
    if r.status_code != 200:
        raise Unavailable(f"HTTP {r.status_code}")
    rows = (r.json().get("web") or {}).get("results") or []
    return [_row(x.get("title"), x.get("url"), x.get("description"), x.get("page_age") or "") for x in rows]


def _ddgs_text(query: str, limit: int, region: str, fresh: str) -> list[dict]:
    from ddgs import DDGS  # type: ignore

    kw = {"max_results": limit}
    if region:
        kw["region"] = region
    if fresh:
        kw["timelimit"] = fresh
    return [_row(x.get("title"), x.get("href"), x.get("body")) for x in DDGS(timeout=6).text(query, **kw)]


def meta(query: str, limit: int, lang: str, fresh: str, key: str = "") -> list[dict]:
    """The keyless metasearch, held to META_SECONDS: an engine that hangs must not hang the answer."""
    try:
        import ddgs  # type: ignore  # noqa: F401
    except ImportError:
        raise Unavailable("the ddgs package is not installed")
    region = {"en": "us-en", "bg": "bg-bg"}.get(lang, "")
    box: dict = {}

    def work():
        for where in ([region, ""] if region else [""]):  # some engines know few regions: once more without one
            try:
                box["rows"] = _ddgs_text(query, limit, where, fresh)
            except Exception as e:  # the package raises its own error for "nothing found" and for throttling alike
                box["error"] = e
            if box.get("rows"):
                return

    t = threading.Thread(target=work, daemon=True, name="vaelon-search")
    t.start()
    t.join(META_SECONDS)
    if not box.get("rows"):
        raise Unavailable("the public search engines did not answer")
    return box["rows"]


def encyclopedia(query: str, limit: int, lang: str, fresh: str = "", key: str = "") -> list[dict]:
    """Wikipedia's own search API plus DuckDuckGo's instant answer: official, keyless, never throttled in practice."""
    from .tools.web import UA, _guard

    wiki = "bg" if lang == "bg" else "en"
    api = f"https://{wiki}.wikipedia.org/w/api.php"
    _guard(api)
    rows = []
    r = requests.get(api, params={"action": "query", "list": "search", "srsearch": query, "srlimit": min(limit, 5),
                                  "format": "json"}, headers=UA, timeout=10)
    for x in (r.json().get("query") or {}).get("search") or []:
        rows.append(_row(x.get("title"), f"https://{wiki}.wikipedia.org/wiki/" + str(x.get("title", "")).replace(" ", "_"),
                         x.get("snippet")))  # its timestamp is the last edit, not the date of the facts
    try:
        j = requests.get("https://api.duckduckgo.com/", params={"q": query, "format": "json", "no_html": 1},
                         headers=UA, timeout=8).json()
        if j.get("AbstractText") and j.get("AbstractURL"):
            rows.insert(0, _row(j.get("Heading"), j["AbstractURL"], j["AbstractText"]))
    except ERRORS:
        pass
    return rows


SOURCES = (("Tavily", TAVILY_KEY, tavily), ("Brave Search", BRAVE_KEY, brave), ("web search", "", meta),
           ("Wikipedia", "", encyclopedia))


def sources() -> list[str]:
    """Usable sources right now, best first (for `vaelon doctor` and the settings screen)."""
    out = [name for name, key, _ in SOURCES[:2] if config.env(key)]
    try:
        import ddgs  # type: ignore  # noqa: F401

        out.append("public engines (no key)")
    except ImportError:
        pass
    return out + ["Wikipedia"]


# ---------------------------------------------------------------- ordering

def _site(href: str) -> str:
    host = (urlparse(href).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _same_page(href: str) -> str:
    """One key per page: no scheme, no www, no #fragment, no tracking parameters ("" for something that is no link)."""
    u = urlparse(href)
    if u.scheme not in ("http", "https") or not u.hostname:
        return ""
    keep = "&".join(p for p in u.query.split("&") if p and not re.match(r"(?i)(utm_|fbclid|gclid|ref=|source=)", p))
    return _site(href) + u.path.rstrip("/").lower() + ("?" + keep if keep else "")


def rank(rows: list[dict], query: str, limit: int) -> list[dict]:
    """Drop repeats and empty rows, keep at most two results per site, put the best matches first.
    The engine's own order still counts: a result only moves up when it clearly matches the question better."""
    words = {w for w in re.findall(r"[\w']+", query.lower()) if len(w) > 2 and w not in STOP}
    seen, kept = set(), []
    for pos, r in enumerate(rows):
        key = _same_page(r.get("href", ""))
        if not key or key in seen or not (r.get("title") or r.get("body")):
            continue
        seen.add(key)
        title, body = r.get("title", "").lower(), r.get("body", "").lower()
        hit = sum((2 if w in title else 0) + (1 if w in body else 0) for w in words) / (3 * len(words)) if words else 0
        kept.append((hit * 4 - pos * 0.35, pos, r))
    kept.sort(key=lambda x: (-x[0], x[1]))
    out, per_site = [], {}
    for _, _, r in kept:
        site = _site(r["href"])
        if per_site.get(site, 0) >= 2:
            continue
        per_site[site] = per_site.get(site, 0) + 1
        out.append(r)
        if len(out) >= limit:
            break
    return out


def search(query: str, limit: int = 6, lang: str = "") -> tuple[list[dict], str]:
    """(results [{title, href, body, date}], the source that answered). ([], "") when nothing answered at all."""
    query = re.sub(r"\s+", " ", query or "").strip()
    if not query:
        return [], ""
    fresh = freshness(query)
    for name, key_name, fn in SOURCES:
        key = config.env(key_name) if key_name else ""
        if key_name and not key:
            continue
        for recent in ([fresh, ""] if fresh else [""]):  # nothing recent enough: look again without the time limit
            try:
                rows = rank(fn(query, limit + 4, lang, recent, key), query, limit)
            except (Unavailable, *ERRORS):
                continue  # not answering (or nothing that recent): once more without the time limit, then the next
            if len(rows) >= (3 if recent else 1):
                return rows, name
    return [], ""
