"""Stock market data from the best source you have a key for.

    Twelve Data  (TWELVEDATA_API_KEY, free key)  quotes + daily history, exchanges worldwide
    Finnhub      (FINNHUB_API_KEY, free key)     real-time quote of US stocks; no free history
    Yahoo Finance (no key)                       unofficial public chart data - the fallback, can break any day

Order: Twelve Data, then whichever of the other two fits the question (history -> Yahoo first, a quote ->
Finnhub first). A source that fails, is out of quota or does not know the symbol is skipped silently.
Keys are stored with `vaelon key set`, travel in a request HEADER (never in the address) and are bound to their
own host (providers.KEY_HOSTS). Data, not advice.
"""
from __future__ import annotations

import re
import time
from urllib.parse import quote

import requests

from . import config

TD = "https://api.twelvedata.com"
FH = "https://finnhub.io/api/v1"
YH = "https://query1.finance.yahoo.com"
TD_KEY, FH_KEY = "TWELVEDATA_API_KEY", "FINNHUB_API_KEY"
INDEX = {"^GSPC": "SPX", "^IXIC": "IXIC", "^DJI": "DJI", "^NDX": "NDX", "^RUT": "RUT"}  # Yahoo style -> Twelve Data
KINDS = ("common stock", "etf", "index", "depositary receipt", "reit", "mutual fund", "digital currency")
ERRORS = (requests.RequestException, KeyError, ValueError, TypeError, IndexError)


class Unavailable(Exception):
    """This source cannot answer (no key, quota, unknown symbol, plan too small): try the next one."""


def _call(url: str, params: dict, headers: dict | None = None):
    from .tools.web import UA, _guard

    _guard(url)
    r = requests.get(url, params=params, headers={**UA, **(headers or {})}, timeout=15, allow_redirects=False)
    try:
        data = r.json()
    except ValueError:
        raise Unavailable(f"HTTP {r.status_code}")
    if r.status_code >= 400 or (isinstance(data, dict) and (data.get("status") == "error" or data.get("error"))):
        raise Unavailable(f"HTTP {r.status_code}")  # the body may quote the key back: never pass it on
    return data


def _clean(symbol: str) -> str:
    return re.sub(r"[^A-Za-z0-9.^=/-]", "", symbol).upper()


def _day(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}"  # 2026-11-11 -> 11.11


# ---------------------------------------------------------------- Twelve Data

def _td_symbol(sym: str) -> str:
    if sym in INDEX:
        return INDEX[sym]
    if re.fullmatch(r"[A-Z0-9]{2,10}-(USD|EUR|USDT)", sym):
        return sym.replace("-", "/")  # BTC-USD -> BTC/USD
    if sym.startswith("^") or "=" in sym:
        raise Unavailable("symbol style not known to Twelve Data")
    return sym


def td_history(sym: str, days: int, key: str) -> dict:
    auth = {"Authorization": "apikey " + key}
    s = _td_symbol(sym)
    series = _call(TD + "/time_series", {"symbol": s, "interval": "1day", "outputsize": days + 1, "order": "asc"}, auth)
    rows = [(_day(v["datetime"]), round(float(v["close"]), 2)) for v in series["values"]]
    if not rows:
        raise Unavailable("no rows")
    name, price = s, rows[-1][1]
    try:  # the name and the live price cost one more credit; without them the answer is still right
        q = _call(TD + "/quote", {"symbol": s}, auth)
        name, price = q.get("name") or s, round(float(q["close"]), 2)
    except (Unavailable, *ERRORS):
        pass
    return {"symbol": sym, "name": name, "currency": (series.get("meta") or {}).get("currency", ""), "price": price,
            "closes": rows[-(days + 1):], "source": "Twelve Data"}


def td_search(name: str, key: str) -> str | None:
    found = _call(TD + "/symbol_search", {"symbol": name, "outputsize": 12}, {"Authorization": "apikey " + key})
    hits = [h for h in found.get("data") or [] if str(h.get("instrument_type", "")).lower() in KINDS and h.get("symbol")]
    home = [h for h in hits if h.get("country") == "United States"]  # the same company is listed on many exchanges
    best = (home or hits or [None])[0]
    return best["symbol"] if best else None


# ---------------------------------------------------------------- Finnhub

def fh_history(sym: str, days: int, key: str) -> dict:
    if not re.fullmatch(r"[A-Z]{1,5}(\.[A-Z])?", sym):
        raise Unavailable("Finnhub's free quote covers US stocks only")
    q = _call(FH + "/quote", {"symbol": sym}, {"X-Finnhub-Token": key})
    if not q.get("c") or not q.get("pc"):
        raise Unavailable("unknown symbol")  # it answers zeros instead of an error
    today = time.strftime("%d.%m", time.gmtime(q.get("t") or time.time()))
    return {"symbol": sym, "name": sym, "currency": "USD", "price": round(float(q["c"]), 2),
            "closes": [("prev", round(float(q["pc"]), 2)), (today, round(float(q["c"]), 2))], "source": "Finnhub"}


def fh_search(name: str, key: str) -> str | None:
    found = _call(FH + "/search", {"q": name}, {"X-Finnhub-Token": key})
    hits = [h for h in found.get("result") or [] if h.get("symbol") and str(h.get("type", "")).lower() in KINDS + ("",)]
    plain = [h for h in hits if "." not in h["symbol"]]  # AAPL before AAPL.MX
    best = (plain or hits or [None])[0]
    return best["symbol"] if best else None


# ---------------------------------------------------------------- Yahoo (no key)

def yahoo_history(sym: str, days: int, key: str = "") -> dict:
    rng = "5d" if days <= 3 else "1mo" if days <= 19 else "3mo" if days <= 60 else "1y"
    d = _call(f"{YH}/v8/finance/chart/{quote(sym)}", {"range": rng, "interval": "1d"})
    res = (d.get("chart", {}).get("result") or [None])[0]
    if not res:
        raise Unavailable("no data")
    m = res["meta"]
    off = m.get("gmtoffset") or 0
    closes = res.get("indicators", {}).get("quote", [{}])[0].get("close", []) or []
    rows = [(time.strftime("%d.%m", time.gmtime(ts + off)), round(c, 2))
            for ts, c in zip(res.get("timestamp") or [], closes) if c is not None]
    return {"symbol": sym, "name": m.get("longName") or m.get("shortName") or sym, "currency": m.get("currency", ""),
            "price": m.get("regularMarketPrice"), "closes": rows[-(days + 1):], "source": "Yahoo Finance"}


def yahoo_search(name: str, key: str = "") -> str | None:
    d = _call(f"{YH}/v1/finance/search", {"q": name, "quotesCount": 3, "newsCount": 0})
    for q in d.get("quotes", []):
        if q.get("symbol") and q.get("quoteType") in ("EQUITY", "ETF", "INDEX", "CRYPTOCURRENCY", "MUTUALFUND", "FUTURE"):
            return q["symbol"]
    return None


# ---------------------------------------------------------------- the two questions Vaelon asks

def sources() -> list[str]:
    """Which sources are usable right now, best first (for `vaelon doctor` and the settings screen)."""
    return [n for n, k in (("Twelve Data", TD_KEY), ("Finnhub", FH_KEY)) if config.env(k)] + ["Yahoo Finance"]


def _first(steps):
    for fn, key_name, args in steps:
        key = config.env(key_name) if key_name else ""
        if key_name and not key:
            continue
        try:
            got = fn(*args, key)
        except (Unavailable, *ERRORS):
            continue
        if got:
            return got
    return None


def history(symbol: str, days: int = 5) -> dict | None:
    """Price + daily closes for the last `days` trading days (one extra close for the change), with its source."""
    sym = _clean(symbol)
    days = max(1, min(int(days), 250))
    rest = [(fh_history, FH_KEY, (sym, days)), (yahoo_history, "", (sym, days))]
    if days > 1:
        rest.reverse()  # Finnhub has no history on a free key: only when nothing else answers
    return _first([(td_history, TD_KEY, (sym, days))] + rest)


def resolve(name: str) -> str | None:
    """Company / index / fund name -> ticker symbol."""
    return _first([(td_search, TD_KEY, (name,)), (fh_search, FH_KEY, (name,)), (yahoo_search, "", (name,))])
