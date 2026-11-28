"""Recurring invoices (issue #44): a plan - client, lines, every month / quarter / year, on a day - and on that day
Vaelon issues the invoice itself, in the normal unbroken series, makes its PDF and tells the user.
Vaelon NEVER sends it: the user sends it (or not).

    Money > Recurring     "every month invoice Acme 500 EUR for support"  (the model's tool recurring_add)

A plan: client, lines (description, quantity, price in cents), VAT rate (fixed when the plan is made), currency,
notes, language, `every` (monthly / quarterly / yearly), `day` (1-31; a short month uses its last day), days to pay,
`next` (the date of the next invoice), active (pause / resume) and `made` (the periods already invoiced).

Safe to repeat: the invoice carries {"recurring": plan id, "period": the date it was due} in the SAME write that gives
it its number, so a plan that stopped half way (or ran twice at once) finds that invoice and never makes a second one.
When Vaelon was not running on the day, the invoice is made the next time it runs (dated that day, the period printed
on it); at most CATCH_UP periods at once, older ones are only reported.

Stored ENCRYPTED in ~/.vaelon/recurring.enc (per company in company mode), like the invoices.
"""
from __future__ import annotations

import calendar as _cal
import json
import re
import threading
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import bills as B
from .security import vault

FILE = "recurring.enc"
EVERY = {"monthly": 1, "quarterly": 3, "yearly": 12}
CATCH_UP = 3  # periods made at once after Vaelon was off; older missed ones are reported, not invoiced
PER_PASS = 24  # invoices made in one pass of the reminder thread (the rest follow in the next passes, seconds later)
MAX_PLANS = 200
_lock = threading.Lock()
_run_lock = threading.Lock()  # one run at a time: the reminder thread and "Make due invoices now" never race
_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"]
_BG_MONTHS = ["януари", "февруари", "март", "април", "май", "юни", "юли", "август", "септември", "октомври",
              "ноември", "декември"]


# ---------------------------------------------------------------- storage

def _path() -> Path:
    from . import company  # each company keeps its own money files

    return company.data_dir() / FILE


def _empty() -> dict:
    return {"plans": []}


def load(strict: bool = False) -> dict:
    """`strict` (before every write): an unreadable file raises instead of being replaced by an empty one."""
    p = _path()
    if not p.exists():
        return _empty()
    try:
        data = json.loads(vault.decrypt_text(p.read_text("utf-8").strip()))
    except Exception:
        if strict:
            raise RuntimeError(f"{FILE} could not be read, so nothing was changed (the file is left as it is)")
        return _empty()
    if not isinstance(data, dict) or not isinstance(data.get("plans"), list):
        return _empty()
    return {"plans": [p for p in data["plans"] if isinstance(p, dict)]}


def _store(data: dict) -> None:
    _path().parent.mkdir(parents=True, exist_ok=True)
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(vault.encrypt_text(json.dumps(data, ensure_ascii=False)), "utf-8")
    vault.replace(tmp, _path())


def _change(fn):
    with _lock:
        data = load(strict=True)
        out = fn(data)
        _store(data)
        return out


def snapshot() -> dict:
    return json.loads(json.dumps(load(strict=True)))


def restore_all(data: dict, today: date | None = None) -> None:
    """Undo: the plans go back to the snapshot - but what was already invoiced stays invoiced: a plan's `next` never
    moves back, its `made` list keeps the newer periods, and a plan that comes back to life (an undone delete or pause)
    starts at its next date from today - never a pile of invoices for the time it was gone or paused."""
    today = today or date.today()
    with _lock:
        now = {p["id"]: p for p in load(strict=True)["plans"]}
        data = json.loads(json.dumps(data))
        for p in data.get("plans", []):
            cur = now.get(p["id"])
            if cur:
                p["next"] = max(p["next"], cur["next"])
                seen = {m["period"] for m in p.get("made", [])}
                p["made"] = (p.get("made", []) + [m for m in cur.get("made", []) if m["period"] not in seen])[-24:]
            if p.get("active") and (not cur or not cur.get("active")) and p.get("next"):
                p["next"] = max(p["next"], first_date(p["day"], p["every"], today, _month_of(p)).isoformat())
        _store({"plans": data.get("plans", [])})


# ---------------------------------------------------------------- dates

def _on(y: int, m: int, day: int) -> date:
    return date(y, m, min(day, _cal.monthrange(y, m)[1]))


def _month_of(p: dict) -> int:
    """The month a quarterly / yearly plan is anchored to (its first invoice's month)."""
    return int(p.get("month") or date.fromisoformat(p["next"]).month)


def first_date(day: int, every: str, start: date, month: int | None = None) -> date:
    """The first invoice date on or after `start`: `day` of this month (or of `month` for quarterly / yearly plans
    anchored to it), else of the next period."""
    step = EVERY[every]
    if month is None:
        d = _on(start.year, start.month, day)
        return d if d >= start else after(d, every, day)
    y = start.year
    d = _on(y, month, day)
    while d > start:  # go back to the period that holds `start`, then forward to the first date >= start
        d = before(d, every, day)
    while d < start:
        d = after(d, every, day)
    return d


def after(d: date, every: str, day: int) -> date:
    y, m = divmod(d.month - 1 + EVERY[every], 12)
    return _on(d.year + y, m + 1, day)


def before(d: date, every: str, day: int) -> date:
    y, m = divmod(d.month - 1 - EVERY[every], 12)
    return _on(d.year + y, m + 1, day)


def period_text(p: dict, when: date, bg: bool = False) -> str:
    """What the invoice is for, printed on it: "December 2026" / "Dec 2026 - Feb 2027" / "2026" when the plan runs on
    the 1st, else the exact dates ("2026-12-15 - 2027-01-14")."""
    end = after(when, p["every"], p["day"]) - timedelta(days=1)
    if when.day != 1 or end.day != _cal.monthrange(end.year, end.month)[1]:
        return f"{_day(when, bg)} - {_day(end, bg)}"
    names = _BG_MONTHS if bg else _MONTHS
    if p["every"] == "monthly":
        return f"{names[when.month - 1]} {when.year}"
    if p["every"] == "yearly" and when.month == 1:
        return str(when.year)
    a, b = names[when.month - 1][:3], names[end.month - 1][:3]
    return f"{a} - {b} {when.year}" if when.year == end.year else f"{a} {when.year} - {b} {end.year}"


def _day(d: date, bg: bool) -> str:
    return f"{d.day:02d}.{d.month:02d}.{d.year}" if bg else d.isoformat()


# ---------------------------------------------------------------- plans

def _rate(vat_rate) -> str:
    me = B.load()["me"]
    rate = vat_rate if vat_rate not in (None, "") else me.get("vat_rate", "20" if me.get("vat_id") else "0")
    try:
        r = Decimal(str(rate).replace(",", ".").strip(" %"))
    except InvalidOperation:
        raise ValueError("VAT must be a number, e.g. 20")
    if not r.is_finite() or not 0 <= r <= 50 or r != r.quantize(Decimal("0.01")):
        raise ValueError("VAT must be between 0 and 50 %")
    return str(r.normalize()) if r != r.to_integral() else str(int(r))


def new_plan(client: dict, items: list[dict], every: str = "monthly", day: int | None = None, vat_rate=None,
             due_days: int = 14, currency: str = "", notes: str = "", lang: str = "en", start: date | None = None,
             today: date | None = None) -> dict:
    """Store a plan. Its first invoice is made on `day` of this period (if still ahead) or of the next one; `start`
    moves the first one later. Nothing is invoiced here."""
    today = today or date.today()
    client = {k: re.sub(r"\s+", " ", str(client.get(k, ""))).strip()[:B.PROFILE_FIELDS.get(k, 200)]
              for k in ("name", "address", "company_id", "vat_id", "person", "email")}
    if not client["name"]:
        raise ValueError("the plan needs the client's name")
    if client["email"]:
        from .tools.comms import _EMAIL

        if not _EMAIL.match(client["email"]):
            raise ValueError("that is not an email address")
    if not items or not isinstance(items, list):
        raise ValueError("the plan needs at least one line")
    rows = []
    for it in items[:100]:
        desc = re.sub(r"\s+", " ", str(it.get("desc", ""))).strip()[:200]
        price = int(it.get("price", 0))
        if not desc or price <= 0 or price > 10**12:
            raise ValueError("every line needs a description and a price above 0")
        rows.append({"desc": desc, "qty": B.qty_of(it.get("qty") or 1), "price": price})
    every = str(every or "monthly").lower()
    if every not in EVERY:
        raise ValueError("every must be monthly, quarterly or yearly")
    start = start or today
    if start < today:
        raise ValueError("the first invoice cannot be in the past")
    if start > today + timedelta(days=400):
        raise ValueError("the first invoice must be within about a year")
    day = int(day) if day not in (None, "") else start.day
    if not 1 <= day <= 31:
        raise ValueError("the day must be 1-31 (a shorter month uses its last day)")
    days = int(due_days) if str(due_days).strip().isdigit() else 14
    days = max(0, min(365, days))
    me = B.load()["me"]
    if not me.get("name"):
        raise ValueError("first fill in your business details (Money > My business, or say: my business is called ...)")
    cur = (currency or me.get("currency") or "EUR").upper()
    if cur not in B.CURRENCIES:
        raise ValueError("currency must be one of " + ", ".join(B.CURRENCIES))
    rate = _rate(vat_rate)
    nxt = first_date(day, "monthly", start)  # the first such day from the start; then every month / quarter / year

    def go(data):
        if len(data["plans"]) >= MAX_PLANS:
            raise ValueError(f"at most {MAX_PLANS} plans")
        p = {"id": uuid.uuid4().hex[:6], "client": client, "items": rows, "vat_rate": rate, "currency": cur,
             "notes": str(notes or "").strip()[:400], "lang": "bg" if lang == "bg" else "en", "every": every,
             "day": day, "month": nxt.month, "due_days": days, "next": nxt.isoformat(), "active": True,
             "made": [], "created": today.isoformat(), "error": "", "warned": ""}
        data["plans"].append(p)
        return dict(p)

    return _change(go)


def get(key: str) -> dict | None:
    key = str(key or "").strip()
    return next((p for p in load()["plans"] if p["id"] == key), None)


def find(words: str) -> dict:
    """One plan: by id, else the only one whose client is named."""
    p = get(words)
    if p:
        return p
    w = str(words or "").strip().lower()
    if not w:
        raise ValueError("say which plan (its client)")
    plans = load()["plans"]
    hits = [x for x in plans if x["client"]["name"].lower() == w] or [
        x for x in plans if re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", x["client"]["name"].lower())]
    if not hits:
        raise ValueError("no recurring invoice matches that (see recurring_list)")
    if len(hits) > 1:
        raise ValueError("several plans match: " + ", ".join(f"{x['client']['name']} [{x['id']}]" for x in hits[:8])
                         + " - say the id")
    return hits[0]


def set_active(pid: str, on: bool, today: date | None = None) -> dict | None:
    """Pause or resume. Resuming never invoices the paused time: the next invoice is the next date from today."""
    today = today or date.today()

    def go(data):
        for p in data["plans"]:
            if p["id"] == pid:
                if on and not p["active"]:
                    p["next"] = max(p["next"], first_date(p["day"], p["every"], today, _month_of(p)).isoformat())
                p["active"] = bool(on)
                return dict(p)
        return None

    return _change(go)


def remove(pid: str) -> dict | None:
    """Delete a plan. The invoices it made stay (they are invoices like any other)."""
    def go(data):
        for p in data["plans"]:
            if p["id"] == pid:
                data["plans"].remove(p)
                return dict(p)
        return None

    return _change(go)


def mark_outside(pid: str) -> None:
    """The plan was written after outside content: its invoices carry `src` too (registry.outside_shown)."""
    _note(pid, src="chat-outside")


def _advance(pid: str, period: str, inv: dict | None, nxt: str, error: str = "") -> None:
    def go(data):
        for p in data["plans"]:
            if p["id"] == pid:
                if nxt > p["next"]:
                    p["next"] = nxt
                if inv and not any(m["period"] == period for m in p["made"]):
                    p["made"] = (p["made"] + [{"period": period, "invoice": inv["id"], "number": inv["number"]}])[-24:]
                p["error"] = error
                return

    _change(go)


def _note(pid: str, **fields) -> None:
    def go(data):
        for p in data["plans"]:
            if p["id"] == pid:
                p.update(fields)

    _change(go)


# ---------------------------------------------------------------- the run (reminder thread, or the app's button)

def invoice_of(pid: str, period: str) -> dict | None:
    """The invoice a plan made for a period (void ones too: a voided one is never made again)."""
    return next((i for i in B.load()["invoices"] if i.get("recurring") == pid and i.get("period") == period), None)


def _pdf(cfg, inv: dict) -> str:
    from .registry_ctx import ctx_for
    from .tools.create import _save

    return _save(ctx_for(cfg), f"Invoice {inv['number']} {inv['client'].get('name', '')}", ".pdf",
                 lambda path: B.invoice_pdf(inv, path), quiet=True)


BUSY = "Vaelon is making the recurring invoices right now - try again in a moment"


def run_due(cfg, now: datetime | None = None, toast: bool = True, asked: bool = False) -> list[str]:
    """Make every invoice that is due (each period once), make the PDFs still missing, and say so. Returns the
    messages. Nothing is ever sent. The reminder thread works 08:00-21:59 only (like every other notice); `asked` (the
    app's "Make the invoices due now") works at any hour and waits for a pass that is running."""
    from . import company, reminders

    now = now or datetime.now()
    today = now.date()
    said = []
    if not asked and not 8 <= now.hour < 22:
        return []
    got = _run_lock.acquire(timeout=20) if asked else _run_lock.acquire(blocking=False)
    if not got:
        return [BUSY] if asked else []
    try:
        made = 0
        for p in load()["plans"]:
            if made >= PER_PASS:
                break
            if not p.get("active") or not p.get("next") or date.fromisoformat(p["next"]) > today:
                continue
            due, d = [], date.fromisoformat(p["next"])
            while d <= today and len(due) < 400:
                due.append(d)
                d = after(d, p["every"], p["day"])
            skipped, due = due[:-CATCH_UP], due[-CATCH_UP:]
            try:
                if skipped:  # moved past FIRST: a failure below must not report these again every few seconds
                    _advance(p["id"], "", None, due[0].isoformat())
                    said.append(f"{len(skipped)} older period(s) of the plan for {p['client']['name']} were not "
                                f"invoiced (from {skipped[0].isoformat()}; Vaelon was not running) - make them by hand "
                                "if they are owed")
                for when in due:
                    period = when.isoformat()
                    inv = invoice_of(p["id"], period)
                    if not inv:
                        bg = p.get("lang") == "bg"
                        label = ("Период: " if bg else "Period: ") + period_text(p, when, bg) + "."
                        inv = B.new_invoice(p["client"], p["items"], p["vat_rate"], p["due_days"], p["currency"],
                                            (label + " " + p.get("notes", "")).strip(), p.get("lang", "en"), today,
                                            link={"recurring": p["id"], "period": period,
                                                  **({"src": p["src"]} if p.get("src") else {})})
                        if not inv.pop("existing", False):
                            made += 1
                            total = B.money(B.invoice_totals(inv)[2], inv["currency"])
                            late = "" if when == today else f" (it was due on {period}; Vaelon was not running then)"
                            said.append(f"invoice no. {inv['number']} for {p['client']['name']}: {total} was made by the "
                                        f"recurring plan{late}. It was NOT sent - check it and send it yourself")
                            if company.enabled() and getattr(company._local, "system", False):
                                from . import journal  # the thread's own invoice: in the journal too, by "Vaelon"

                                journal.add("invoice issued (recurring)",
                                            f"no. {inv['number']} {p['client']['name']} {total}, period {period}")
                    _advance(p["id"], period, inv, after(when, p["every"], p["day"]).isoformat())
            except Exception as e:
                msg = str(e)[:300]
                try:
                    if (get(p["id"]) or {}).get("warned") != today.isoformat():  # once a day, never every few seconds
                        _note(p["id"], error=msg, warned=today.isoformat())
                        said.append(f"the recurring invoice for {p['client']['name']} could not be made: {msg}")
                except Exception:
                    pass
        said += _missing_pdfs(cfg, now)
    finally:
        _run_lock.release()
    for text in shown_notices(said):
        reminders.notify("Vaelon - recurring invoice", text, "reminder", toast)
    return said


def shown_notices(texts: list[str], most: int = 3) -> list[str]:
    """At most `most` notices at once: many at the same moment become one summary (one toast, not hundreds)."""
    if len(texts) <= most:
        return texts
    return texts[:most - 1] + [f"and {len(texts) - most + 1} more - see Money in the app"]


_pdf_tries: dict[str, float] = {}  # invoice id -> when its PDF was last tried (at most once an hour)


def _missing_pdfs(cfg, now: datetime) -> list[str]:
    said, tried = [], 0
    plans = {p["id"] for p in load()["plans"]}
    for inv in B.load()["invoices"]:
        if tried >= PER_PASS:
            break  # the rest in the next pass: one pass never makes hundreds of PDFs
        if not inv.get("recurring") or inv["status"] == "void" or inv.get("file"):
            continue
        if inv["recurring"] not in plans and inv["issued"] < (now.date() - timedelta(days=31)).isoformat():
            continue  # an old one of a deleted plan: left alone
        last = _pdf_tries.get(inv["id"])
        if last is not None and now.timestamp() - last < 3600:
            continue
        first = last is None
        tried += 1
        _pdf_tries[inv["id"]] = now.timestamp()
        path = ""
        try:
            path = _pdf(cfg, inv)
            B.update_invoice(inv["id"], file=path)
        except Exception as e:  # the invoice stays (its number is used); the PDF is tried again in an hour
            if path:
                Path(path).unlink(missing_ok=True)
            if first:
                said.append(f"the PDF of invoice no. {inv['number']} could not be made ({str(e)[:160]}) - Vaelon "
                            "tries again in an hour")
    return said


# ---------------------------------------------------------------- text

def plan_line(p: dict, ids: bool = True) -> str:
    total = B.invoice_totals({"items": p["items"], "vat_rate": p["vat_rate"]})[2]
    state = f"next {p['next']}" if p["active"] else "paused"
    last = f", last no. {p['made'][-1]['number']}" if p.get("made") else ""
    err = f" - PROBLEM: {p['error']}" if p.get("error") else ""
    note = f" - note on each invoice: {p['notes']}" if p.get("notes") else ""
    return (f"{p['client']['name']}: {B.money(total, p['currency'])} {p['every']} on day {p['day']} ({state}{last}){note}{err}"
            + (f"  [id {p['id']}]" if ids else ""))


def list_text(ids: bool = True) -> str:
    plans = load()["plans"]
    if not plans:
        return "no recurring invoices (make one in Money > Recurring, or ask: every month invoice Acme 500 EUR)"
    return "\n".join("• " + plan_line(p, ids) for p in sorted(plans, key=lambda p: (not p["active"], p["next"])))


# ---------------------------------------------------------------- company mode: who may change what (and the journal)
from . import company as _co  # noqa: E402

new_plan = _co.guarded(new_plan, "invoices.write", "recurring invoice planned",
                       lambda r, a, k: f"{r['client']['name']} {r['every']} day {r['day']}")
set_active = _co.guarded(set_active, "invoices.write", "recurring invoice paused / resumed",
                         lambda r, a, k: f"{r['client']['name']}: {'on' if r['active'] else 'paused'}" if r else "")
remove = _co.guarded(remove, "invoices.write", "recurring invoice deleted", lambda r, a, k: r["client"]["name"] if r else "")
restore_all = _co.guarded(restore_all, "invoices.write", "undo", lambda r, a, k: "recurring invoices")
