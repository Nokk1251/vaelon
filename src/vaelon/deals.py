"""Deals: the sales you are working on, from the first contact to won (or lost).

    "нова сделка с Acme: уеб сайт 5000 евро"   "new deal with Acme: website 5000 EUR"
    "Acme е на оферта"   "move Acme to negotiation"   "спечелихме Acme"   "lost the Acme deal"   "как вървят сделките?"

A deal has a client, what it is about, a value, a stage, an expected close date, a next step with a date (Vaelon
reminds you on that day) and a short log of notes. Stages: lead -> contacted -> proposal -> negotiation -> won / lost,
each with a usual chance of closing (10 / 20 / 50 / 75 / 100 / 0 %), so the pipeline has a weighted value.
A won deal can become an invoice in one step (bills.py numbers it). Stored ENCRYPTED in ~/.vaelon/deals.enc.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from . import bills as B
from . import config
from .security import vault

FILE = "deals.enc"
STAGES = ("lead", "contacted", "proposal", "negotiation", "won", "lost")
OPEN = STAGES[:4]
CHANCE = {"lead": 10, "contacted": 20, "proposal": 50, "negotiation": 75, "won": 100, "lost": 0}
_BG = {"lead": "потенциална", "contacted": "има контакт", "proposal": "оферта", "negotiation": "преговори",
       "won": "спечелена", "lost": "загубена"}
STAGE_WORDS = {
    "lead": r"lead|prospect|потенциал\w*|лийд",
    "contacted": r"contacted|in touch|first call|контакт\w*|свързахме се|говорихме",
    "proposal": r"proposal|offer|quote|quotation|оферт\w*|предложение",
    "negotiation": r"negotiat\w*|talks|contract|преговор\w*|договор\w*",
    "won": r"won|win|signed|closed won|deal done|спечел\w*|подписа\w*|приеха|сключ\w*",
    "lost": r"lost|lose|declined|rejected|said no|cancel\w*|загуб\w*|отказа\w*|отпадна\w*",
}
STALE_DAYS = 14
_lock = threading.Lock()


def stage_of(text: str) -> str | None:
    low = (text or "").lower().strip()
    if low in STAGES:
        return low
    for st in ("won", "lost", "negotiation", "proposal", "contacted", "lead"):  # strongest first
        if re.search(r"(?i)(?<![\w])(?:" + STAGE_WORDS[st] + r")(?![\w])", low):
            return st
    return None


def stage_label(st: str, bg: bool) -> str:
    return _BG[st] if bg else st


# ---------------------------------------------------------------- storage

def _path() -> Path:
    from . import company  # each company keeps its own money files (the personal workspace: ~/.vaelon as before)

    return company.data_dir() / FILE


def load(strict: bool = False) -> list[dict]:
    """`strict` (before every write): an unreadable file raises instead of being replaced by an empty one."""
    p = _path()
    if not p.exists():
        return []
    try:
        data = json.loads(vault.decrypt_text(p.read_text("utf-8").strip()))
        return data.get("deals", []) if isinstance(data, dict) else []
    except Exception:
        if strict:
            raise RuntimeError(f"{FILE} could not be read, so nothing was changed (the file is left as it is)")
        return []


def _store(items: list[dict]) -> None:
    _path().parent.mkdir(parents=True, exist_ok=True)
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(vault.encrypt_text(json.dumps({"deals": items}, ensure_ascii=False)), "utf-8")
    vault.replace(tmp, _path())


def snapshot() -> list[dict]:
    return json.loads(json.dumps(load(strict=True)))


def restore_all(items: list[dict]) -> None:
    with _lock:
        _store(items)


def _change(fn):
    with _lock:
        items = load(strict=True)
        out = fn(items)
        _store(items)
        return out


# ---------------------------------------------------------------- deals

def add(client: str, title: str = "", value: int = 0, currency: str = "EUR", stage: str = "lead",
        close: date | None = None, next_step: str = "", next_date: date | None = None, contact: str = "",
        note: str = "") -> dict:
    client = re.sub(r"\s+", " ", str(client)).strip(" ,.:;-")[:120]
    if not client:
        raise ValueError("a deal needs a client (who you are selling to)")
    if stage not in STAGES:
        raise ValueError("stage must be one of " + ", ".join(STAGES))
    value, currency = B.euro_first(int(value), currency)
    if currency not in B.CURRENCIES:
        raise ValueError("currency must be one of " + ", ".join(B.CURRENCIES))
    if value < 0:
        raise ValueError("the value cannot be negative")
    today = date.today().isoformat()
    d = {"id": uuid.uuid4().hex[:6], "client": client, "title": re.sub(r"\s+", " ", str(title)).strip()[:200],
         "value": int(value), "currency": currency, "stage": stage, "created": today, "updated": today,
         "close": close.isoformat() if close else "", "next_step": str(next_step).strip()[:200],
         "next_date": next_date.isoformat() if next_date else "", "contact": str(contact).strip()[:120],
         "notes": [{"date": today, "text": str(note).strip()[:500]}] if str(note).strip() else [],
         "alerted": "", "won_on": today if stage == "won" else "", "lost_reason": "", "invoice": ""}
    return _change(lambda items: items.append(d) or d)


def get(did: str) -> dict | None:
    return next((d for d in load() if d["id"] == did), None)


def update(did: str, **changes) -> dict | None:
    """Change fields. A new stage stamps won_on; a new next_date re-arms the reminder."""
    def go(items):
        for d in items:
            if d["id"] != did:
                continue
            if "stage" in changes:
                if changes["stage"] not in STAGES:
                    raise ValueError("stage must be one of " + ", ".join(STAGES))
                if changes["stage"] == "won" and d["stage"] != "won":
                    d["won_on"] = date.today().isoformat()
                elif changes["stage"] != "won":
                    d["won_on"] = ""
                if changes["stage"] in ("won", "lost"):
                    d["next_step"], d["next_date"] = "", ""
            # no reset of `alerted` is needed: its keys carry the date, so a new date re-arms by itself
            note = changes.pop("note", "")
            d["updated"] = date.today().isoformat()
            d.update(changes)
            if note:
                d["notes"] = (d.get("notes") or []) + [{"date": date.today().isoformat(), "text": str(note).strip()[:500]}]
                d["notes"] = d["notes"][-50:]
            return dict(d)
        return None

    return _change(go)


def remove(did: str) -> dict | None:
    def go(items):
        gone = next((d for d in items if d["id"] == did), None)
        if gone:
            items.remove(gone)
        return gone

    return _change(go)


def match(words: str, open_only: bool = False) -> list[dict]:
    """Deals whose client, title or contact fit the words ('Acme', 'the website deal'). Best match first."""
    low = (words or "").lower()
    terms = [t for t in re.findall(r"[\wа-я]{3,}", low)
             if t not in {"deal", "deals", "the", "with", "сделка", "сделката", "сделки", "сделките", "със", "for", "and"}]
    out = []
    for d in load():
        if open_only and d["stage"] not in OPEN:
            continue
        hay = " ".join([d["client"], d["title"], d.get("contact", "")]).lower()
        score = sum(1 for t in terms if t in hay) + (3 if d["client"].lower() in low else 0)
        if score:
            out.append((score, d["stage"] in OPEN, d["updated"], d))
    out.sort(key=lambda r: (r[0], r[1], r[2]), reverse=True)
    return [r[3] for r in out]


# ---------------------------------------------------------------- the pipeline in words

def weighted(d: dict) -> int:
    return int((Decimal(d["value"]) * CHANCE[d["stage"]] / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def deal_line(d: dict, bg: bool, ids: bool = True, today: date | None = None) -> str:
    today = today or date.today()
    value = B.money(d["value"], d["currency"], bg) if d["value"] else ("без сума" if bg else "no value yet")
    what = f" - {d['title']}" if d["title"] else ""
    extra = ""
    if d["stage"] in OPEN and (d.get("next_step") or d.get("next_date")):
        when = ""
        if d.get("next_date"):
            nd = date.fromisoformat(d["next_date"])
            when = (" (" + ("ЗАКЪСНЯЛО " if nd < today and bg else "LATE " if nd < today else "") + B.day_text(nd, bg, today) + ")")
        extra = (f"; следва: {d['next_step'] or 'действие'}{when}" if bg else f"; next: {d['next_step'] or 'follow up'}{when}")
    elif d["stage"] == "lost" and d.get("lost_reason"):
        extra = f" ({d['lost_reason']})"
    if d["stage"] == "won" and d.get("invoice"):
        extra += f"; фактура № {d['invoice']}" if bg else f"; invoice no. {d['invoice']}"
    return f"{d['client']}{what}: {value} [{stage_label(d['stage'], bg)}]{extra}" + (f"  [id {d['id']}]" if ids else "")


def pipeline_text(bg: bool, ids: bool = True, today: date | None = None) -> str:
    today = today or date.today()
    items = load()
    open_ = [d for d in items if d["stage"] in OPEN]
    if not items:
        return ("Нямаш записани сделки. Кажи например „нова сделка с Acme: уеб сайт 5000 евро“." if bg
                else "No deals yet. Say e.g. \"new deal with Acme: website 5000 EUR\".")
    tot, wt = {}, {}
    for d in open_:
        tot[d["currency"]] = tot.get(d["currency"], 0) + d["value"]
        wt[d["currency"]] = wt.get(d["currency"], 0) + weighted(d)
    lines = [(f"Отворени сделки: {len(open_)}, общо {B.totals_text(tot, bg)} (очаквано {B.totals_text(wt, bg)})" if bg
              else f"Open deals: {len(open_)}, {B.totals_text(tot, bg)} in total ({B.totals_text(wt, bg)} expected)")]
    for st in reversed(OPEN):  # the closest to closing first
        for d in sorted((x for x in open_ if x["stage"] == st), key=lambda x: -x["value"]):
            lines.append("• " + deal_line(d, bg, ids, today))
    late = [d for d in open_ if d.get("next_date") and date.fromisoformat(d["next_date"]) < today]
    stale = [d for d in open_ if not d.get("next_date") and (today - date.fromisoformat(d["updated"])).days >= STALE_DAYS]
    if late:
        lines.append(("Закъснели следващи стъпки: " if bg else "Late next steps: ") + ", ".join(d["client"] for d in late) + ".")
    if stale:
        lines.append((f"Без движение от {STALE_DAYS}+ дни: " if bg else f"No movement for {STALE_DAYS}+ days: ")
                     + ", ".join(d["client"] for d in stale) + ".")
    year = str(today.year)
    won = [d for d in items if d["stage"] == "won" and d.get("won_on", "")[:4] == year]
    lost = [d for d in items if d["stage"] == "lost" and d.get("updated", "")[:4] == year]
    if won or lost:
        got = {}
        for d in won:
            got[d["currency"]] = got.get(d["currency"], 0) + d["value"]
        rate = round(100 * len(won) / (len(won) + len(lost)))
        lines.append((f"През {year}: спечелени {len(won)} ({B.totals_text(got, bg)}), загубени {len(lost)}, успеваемост {rate} %."
                      if bg else f"In {year}: won {len(won)} ({B.totals_text(got, bg)}), lost {len(lost)}, win rate {rate} %."))
    return "\n".join(lines)


# ---------------------------------------------------------------- follow-up reminders

def fire_due(now: datetime | None = None, toast: bool = True) -> list[str]:
    """On a next step's date (from 08:00) and once when an expected close date has passed with the deal still open.
    Called by the reminder thread (reminders.watch)."""
    from . import reminders

    now = now or datetime.now()
    if not 8 <= now.hour < 22:
        return []
    today = now.date()
    fired = []
    with _lock:
        items, changed = load(strict=True), False
        for d in items:
            if d["stage"] not in OPEN:
                continue
            keys = set(filter(None, (d.get("alerted") or "").split("|")))
            if d.get("next_date") and date.fromisoformat(d["next_date"]) <= today and f"n{d['next_date']}" not in keys:
                keys.add(f"n{d['next_date']}")
                fired.append(f"{d['client']}: {d.get('next_step') or 'follow up'}"
                             + (f" ({d['title']})" if d["title"] else ""))
            if d.get("close") and date.fromisoformat(d["close"]) < today and f"c{d['close']}" not in keys:
                keys.add(f"c{d['close']}")
                fired.append(f"{d['client']}: the expected close date ({d['close']}) has passed - still {d['stage']}")
            new = "|".join(sorted(keys))
            if new != (d.get("alerted") or ""):
                d["alerted"], changed = new, True
        if changed:
            _store(items)
    for text in fired:
        reminders.notify("Vaelon - deal", text, "reminder", toast)
    return fired


# ---------------------------------------------------------------- won -> invoice

def invoice_items(d: dict) -> list[dict]:
    if not d["value"]:
        raise ValueError("the deal has no value - set it first, or make the invoice with its items")
    return [{"desc": d["title"] or f"Services for {d['client']}", "qty": "1", "price": d["value"]}]


def export_rows() -> list[list]:
    rows = [["Client", "Title", "Value", "Currency", "Stage", "Chance %", "Expected close", "Next step", "Next date",
             "Created", "Won on", "Invoice"]]
    for d in sorted(load(), key=lambda d: (STAGES.index(d["stage"]), d["client"].lower())):
        rows.append([d["client"], d["title"], float(Decimal(d["value"]) / 100), d["currency"], d["stage"], CHANCE[d["stage"]],
                     d["close"], d.get("next_step", ""), d.get("next_date", ""), d["created"], d.get("won_on", ""),
                     d.get("invoice", "")])
    return rows


# ---------------------------------------------------------------- company mode: who may change what (and the journal)
from . import company as _co  # noqa: E402

add = _co.guarded(add, "deals.write", "deal added", lambda r, a, k: f"{r['client']} {r['title']} {B.money(r['value'], r['currency'])}")
update = _co.guarded(update, "deals.write", "deal changed",
                     lambda r, a, k: (r["client"] + ": " + ", ".join(f"{x}={v}" for x, v in k.items() if x not in ("notes",))) if r else "")
remove = _co.guarded(remove, "deals.write", "deal deleted", lambda r, a, k: r["client"] if r else "")
restore_all = _co.guarded(restore_all, "deals.write", "undo", lambda r, a, k: "deals")
