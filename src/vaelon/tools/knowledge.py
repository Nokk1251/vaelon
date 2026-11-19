"""Knowledge tools backed by FREE public APIs that need NO key, NO account and NO payment.

Every call goes through the same SSRF guard + Guardian link check as web browsing, results are capped and
fenced as untrusted data. Sources: Wikipedia, Open-Meteo, Frankfurter (ECB rates), CoinGecko, stock data
(market_data.py: Twelve Data / Finnhub with your free key, else Yahoo Finance), World Bank, arXiv, Open Library, OSV.dev, CISA KEV, NVD, Hacker News (Algolia), FreeToGame.
Data, not advice: finance tools return market data; Vaelon does not give personalised investment advice.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote

from ..security.injection import fence
from .registry import tool
from .web import UA, _guard

import requests

_http = requests.Session()
_http.headers.update(UA)


def _get(url: str, params: dict | None = None, *, as_json: bool = True, timeout: int = 15):
    _guard(url)
    r = _http.get(url, params=params, timeout=timeout, allow_redirects=False)  # a hop would skip the SSRF guard
    r.raise_for_status()
    return r.json() if as_json else r.text


def _out(data, source: str, limit: int = 6000) -> str:
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=1)
    return fence(text[:limit], source)[0]


@tool("wiki", "Encyclopedia summary of any topic from Wikipedia (any language, e.g. lang=bg)",
      {"topic": "subject", "?lang": "bg / en / de ..."}, untrusted=True, group="knowledge")
def wiki(ctx, topic, lang="en"):
    lang = re.sub(r"[^a-z-]", "", str(lang).lower())[:8] or "en"
    wait = 3 if ctx.extra.get("hurry") else 15  # a spoken exchange does not wait for a slow lookup
    hits = _get(f"https://{lang}.wikipedia.org/w/api.php",
                {"action": "opensearch", "search": topic, "limit": 1, "format": "json"}, timeout=wait)
    if not hits[1]:
        return f"no Wikipedia article found for '{topic}'"
    page = _get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(hits[1][0].replace(' ', '_'))}",
                timeout=wait)
    return _out(f"{page.get('title')}\n{page.get('extract', '')}\n{page.get('content_urls', {}).get('desktop', {}).get('page', '')}",
                "wikipedia")


@tool("weather", "Current weather and 3-day forecast for a place (Open-Meteo)", {"place": "city"},
      untrusted=True, group="knowledge")
def weather(ctx, place):
    data = weather_data(place, "bg" if re.search(r"[Ѐ-ӿ]", place) else "en")
    return _out(data, "open-meteo") if data else f"place not found: {place}"


@tool("exchange_rate", "Official exchange rates (European Central Bank via Frankfurter)",
      {"base": "e.g. EUR", "?to": "e.g. BGN,USD"}, untrusted=True, group="knowledge")
def exchange_rate(ctx, base, to=""):
    params = {"from": base.upper()}
    if to:
        params["to"] = to.upper()
    return _out(_get("https://api.frankfurter.app/latest", params), "ecb-frankfurter")


@tool("crypto_price", "Crypto prices and 24h change (CoinGecko public API)", {"coins": "e.g. bitcoin,ethereum"},
      untrusted=True, group="knowledge")
def crypto_price(ctx, coins):
    return _out(_get("https://api.coingecko.com/api/v3/simple/price",
                     {"ids": coins.lower(), "vs_currencies": "usd,eur", "include_24hr_change": "true"}), "coingecko")


def resolve_ticker(name: str) -> str | None:
    """Company / index / fund name -> ticker symbol (Twelve Data or Finnhub with your key, else Yahoo Finance)."""
    from .. import market_data

    return market_data.resolve(name)


def stock_history(symbol: str, days: int = 5) -> dict | None:
    """Price + daily closes for the last `days` trading days (one extra close for the change) and the `source`."""
    from .. import market_data

    return market_data.history(symbol, days)


@tool("stock_quote", "Latest stock/ETF/index price and daily closes (live market data). "
      "Symbol like AAPL, NVDA, ^GSPC, BTC-USD, or a company name", {"symbol": "ticker or company name",
      "?days": "how many trading days of history (default 5)"}, untrusted=True, group="knowledge")
def stock_quote(ctx, symbol, days=5):
    sym = symbol.strip()
    if not re.fullmatch(r"[\^A-Za-z0-9.=-]{1,12}", sym) or (sym.isalpha() and len(sym) > 5):
        sym = resolve_ticker(sym) or sym
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 5
    h = stock_history(sym, days)
    if not h:
        return f"no data for {sym}"
    return _out(h, str(h.get("source", "market data")).lower().replace(" ", "-")) + "\n(market data only - not investment advice)"


def weather_data(place: str, lang: str = "en") -> dict | None:
    geo = _get("https://geocoding-api.open-meteo.com/v1/search", {"name": place, "count": 1, "language": lang})
    if not geo.get("results"):
        return None
    g = geo["results"][0]
    w = _get("https://api.open-meteo.com/v1/forecast", {
        "latitude": g["latitude"], "longitude": g["longitude"], "timezone": "auto", "forecast_days": 3,
        "current": "temperature_2m,apparent_temperature,wind_speed_10m,precipitation,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code"})
    return {"place": g["name"], "country": g.get("country", ""), "now": w.get("current", {}), "daily": w.get("daily", {})}


@tool("country_info", "Facts about a country: capital, region, income level, population, GDP (World Bank)",
      {"country": "ISO code (BG, US, DE...) or English name"}, untrusted=True, group="knowledge")
def country_info(ctx, country):
    code = country.strip()
    if len(code) not in (2, 3) or not code.isalpha():
        allc = _get("https://api.worldbank.org/v2/country", {"format": "json", "per_page": 400})[1]
        match = next((c for c in allc if c["name"].lower() == code.lower()), None)
        match = match or next((c for c in allc if code.lower() in c["name"].lower()), None)
        if not match:
            return f"country not found: {country}"
        code = match["id"]
    meta = _get(f"https://api.worldbank.org/v2/country/{quote(code)}", {"format": "json"})[1][0]
    facts = {"name": meta["name"], "capital": meta.get("capitalCity"), "region": meta["region"]["value"],
             "income_level": meta["incomeLevel"]["value"]}
    for label, ind in (("population", "SP.POP.TOTL"), ("gdp_usd", "NY.GDP.MKTP.CD")):
        rows = _get(f"https://api.worldbank.org/v2/country/{quote(code)}/indicator/{ind}",
                    {"format": "json", "per_page": 5, "mrnev": 1})
        if len(rows) > 1 and rows[1]:
            facts[label] = {"year": rows[1][0]["date"], "value": rows[1][0]["value"]}
    return _out(facts, "worldbank")


@tool("economy_indicator", "World Bank indicator for a country, e.g. GDP (NY.GDP.MKTP.CD), inflation (FP.CPI.TOTL.ZG), "
      "unemployment (SL.UEM.TOTL.ZS)", {"country": "ISO code e.g. BG", "?indicator": "World Bank code"},
      untrusted=True, group="knowledge")
def economy_indicator(ctx, country, indicator="NY.GDP.MKTP.CD"):
    data = _get(f"https://api.worldbank.org/v2/country/{quote(country)}/indicator/{quote(indicator)}",
                {"format": "json", "per_page": 8})
    rows = [{"year": d["date"], "value": d["value"]} for d in (data[1] if len(data) > 1 and data[1] else [])]
    return _out({"indicator": indicator, "country": country, "values": rows}, "worldbank")


@tool("science_papers", "Search scientific papers on arXiv (title, authors, summary, link)", {"query": "topic"},
      untrusted=True, group="knowledge")
def science_papers(ctx, query):
    xml = _get("https://export.arxiv.org/api/query", {"search_query": f"all:{query}", "max_results": 5},
               as_json=False, timeout=25)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for e in ET.fromstring(xml).findall("a:entry", ns):
        out.append({"title": " ".join((e.findtext("a:title", "", ns)).split()),
                    "authors": [a.findtext("a:name", "", ns) for a in e.findall("a:author", ns)][:4],
                    "summary": " ".join((e.findtext("a:summary", "", ns)).split())[:400],
                    "link": e.findtext("a:id", "", ns)})
    return _out(out or "no papers found", "arxiv")


@tool("book_search", "Find books: title, author, year, subjects (Open Library)", {"query": "title or author"},
      untrusted=True, group="knowledge")
def book_search(ctx, query):
    d = _get("https://openlibrary.org/search.json", {"q": query, "limit": 5,
                                                      "fields": "title,author_name,first_publish_year,subject,key"})
    books = [{"title": b.get("title"), "author": b.get("author_name"), "year": b.get("first_publish_year"),
              "subjects": (b.get("subject") or [])[:5], "url": f"https://openlibrary.org{b.get('key', '')}"}
             for b in d.get("docs", [])]
    return _out(books or "no books found", "openlibrary")


@tool("free_games", "Browse free-to-play games by platform/genre (FreeToGame)", {"?platform": "pc / browser",
      "?category": "e.g. shooter, mmorpg, strategy"}, untrusted=True, group="knowledge")
def free_games(ctx, platform="pc", category=""):
    params = {"platform": platform}
    if category:
        params["category"] = category
    games = _get("https://www.freetogame.com/api/games", params)[:10]
    return _out([{k: g.get(k) for k in ("title", "genre", "platform", "short_description", "game_url")} for g in games],
                "freetogame")


@tool("tech_news", "Latest technology/security news and discussions (Hacker News)", {"?query": "topic (optional)"},
      untrusted=True, group="knowledge")
def tech_news(ctx, query=""):
    url = "https://hn.algolia.com/api/v1/search" if query else "https://hn.algolia.com/api/v1/search_by_date"
    d = _get(url, {"query": query, "tags": "story", "hitsPerPage": 10})
    return _out([{"title": h.get("title"), "url": h.get("url"), "points": h.get("points")} for h in d.get("hits", [])],
                "hackernews")


@tool("package_vulns", "Known security vulnerabilities of an open-source package version (OSV.dev)",
      {"name": "package", "?ecosystem": "PyPI / npm / Go / Maven ...", "?version": "version"},
      untrusted=True, group="security")
def package_vulns(ctx, name, ecosystem="PyPI", version=""):
    body = {"package": {"name": name, "ecosystem": ecosystem}}
    if version:
        body["version"] = version
    _guard("https://api.osv.dev/v1/query")
    r = _http.post("https://api.osv.dev/v1/query", json=body, timeout=20)
    r.raise_for_status()
    vulns = r.json().get("vulns", [])
    return _out([{"id": v.get("id"), "summary": v.get("summary"), "aliases": v.get("aliases", [])[:3]}
                 for v in vulns[:15]] or f"no known vulnerabilities for {name} {version}".strip(), "osv.dev")


@tool("exploited_vulns", "Vulnerabilities actively exploited in the wild (CISA KEV catalogue), filter by vendor/product",
      {"?search": "vendor or product, e.g. Microsoft, Chrome"}, untrusted=True, group="security")
def exploited_vulns(ctx, search=""):
    d = _get("https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json", timeout=30)
    items = d.get("vulnerabilities", [])
    if search:
        s = search.lower()
        items = [v for v in items if s in (v.get("vendorProject", "") + " " + v.get("product", "")).lower()]
    items = sorted(items, key=lambda v: v.get("dateAdded", ""), reverse=True)[:12]
    return _out([{k: v.get(k) for k in ("cveID", "vendorProject", "product", "vulnerabilityName", "dateAdded",
                                         "requiredAction")} for v in items], "cisa-kev")


@tool("cve_lookup", "Details of a CVE (NIST NVD): description, severity score, references", {"cve": "e.g. CVE-2024-3094"},
      untrusted=True, group="security")
def cve_lookup(ctx, cve):
    cve = re.sub(r"[^A-Za-z0-9-]", "", cve).upper()
    d = _get("https://services.nvd.nist.gov/rest/json/cves/2.0", {"cveId": cve}, timeout=30)
    vulns = d.get("vulnerabilities", [])
    if not vulns:
        return f"{cve} not found"
    c = vulns[0]["cve"]
    desc = next((x["value"] for x in c.get("descriptions", []) if x.get("lang") == "en"), "")
    metrics = c.get("metrics", {})
    score = next((m[0]["cvssData"].get("baseScore") for k, m in metrics.items() if m), None)
    return _out({"id": cve, "published": c.get("published"), "score": score, "description": desc,
                 "references": [r["url"] for r in c.get("references", [])[:5]]}, "nvd")
