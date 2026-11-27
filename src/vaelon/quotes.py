"""Quotes (offers) to clients that become invoices in one step (issue #43).

    "make a quote for Acme: 10 hours of design at 60 EUR"   "what quotes do I have?"   Money > Quotes

A quote has a client, lines (description, quantity, price), one VAT rate, a currency, a valid-until date and its own
number series (Q-000001, Q-000002 ...) that NEVER touches the unbroken invoice numbering. States: draft -> sent ->
accepted / declined; a draft or sent quote past its valid-until date is shown as expired (Vaelon reminds you a few
days before and once when it expires). "Accepted" makes an invoice with the same lines (bills.py numbers it), and a
linked deal moves to won and keeps both numbers. The PDF looks like the invoice PDF, titled "Quote".

Stored ENCRYPTED in ~/.vaelon/quotes.enc (per company in company mode), like the invoices. Money in cents.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import bills as B
from .security import vault

FILE = "quotes.enc"
STATES = ("draft", "sent", "accepted", "declined", "expired")
SETTABLE = ("draft", "sent", "declined")  # "accepted" only through accept (it makes the invoice); "expired" is a date
REMIND_DAYS = 3
_lock = threading.Lock()


# ---------------------------------------------------------------- storage

def _path() -> Path:
    from . import company  # each company keeps its own money files

    return company.data_dir() / FILE


def _empty() -> dict:
    return {"quotes": [], "next": 1}


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
    if not isinstance(data, dict):
        return _empty()
    base = _empty()
    base.update({k: v for k, v in data.items() if k in base})
    return base


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


def restore_all(data: dict) -> None:
    """Undo: the quotes go back to the snapshot, but a number is never given twice (`next` only grows) and a quote
    that became an invoice stays accepted (the invoice is never taken back - it is voided instead)."""
    with _lock:
        now = load(strict=True)
        data = json.loads(json.dumps(data))
        accepted = {q["id"]: q for q in now["quotes"] if q["status"] == "accepted"}
        have = {q["id"] for q in data.get("quotes", [])}
        data["quotes"] = [accepted.get(q["id"], q) for q in data.get("quotes", [])] + [
            q for q in accepted.values() if q["id"] not in have]
        data["next"] = max(int(data.get("next") or 1), int(now.get("next") or 1))
        _store(data)


# ---------------------------------------------------------------- quotes

def status_of(q: dict, today: date | None = None) -> str:
    """The state to show: a draft or sent quote past its valid-until date is expired."""
    today = today or date.today()
    if q["status"] in ("draft", "sent") and q.get("valid_until") and date.fromisoformat(q["valid_until"]) < today:
        return "expired"
    return q["status"]


def totals(q: dict) -> tuple[int, int, int]:
    """(net, VAT, total) in cents - the same sums the invoice will have."""
    return B.invoice_totals(q)


def new_quote(client: dict, items: list[dict], vat_rate: str | None = None, valid_days: int = 30, currency: str = "",
              notes: str = "", lang: str = "en", deal: str = "", issued: date | None = None) -> dict:
    """Number and store a new quote (a draft). The PDF is made by `quote_pdf`. Needs the business details first."""
    client = {k: re.sub(r"\s+", " ", str(client.get(k, ""))).strip()[:B.PROFILE_FIELDS.get(k, 200)]
              for k in ("name", "address", "company_id", "vat_id", "person", "email")}
    if not client["name"]:
        raise ValueError("the quote needs the client's name")
    if not items:
        raise ValueError("the quote needs at least one line")
    me = B.load()["me"]
    if not me.get("name"):
        raise ValueError("first fill in your business details (Money > My business, or say: my business is called ...)")
    rate = vat_rate if vat_rate not in (None, "") else me.get("vat_rate", "20" if me.get("vat_id") else "0")
    try:
        rate_d = Decimal(str(rate).replace(",", ".").strip(" %"))
    except InvalidOperation:
        raise ValueError("VAT must be a number, e.g. 20")
    if not rate_d.is_finite() or not 0 <= rate_d <= 50 or rate_d != rate_d.quantize(Decimal("0.01")):
        raise ValueError("VAT must be between 0 and 50 %")
    cur = (currency or me.get("currency") or "EUR").upper()
    if cur not in B.CURRENCIES:
        raise ValueError("currency must be one of " + ", ".join(B.CURRENCIES))
    days = max(1, min(365, int(valid_days)))
    issued = issued or date.today()

    def go(data):
        used = {q["number"] for q in data["quotes"]}
        n = int(data.get("next") or 1)
        while f"Q-{n:06d}" in used:
            n += 1
        q = {"id": uuid.uuid4().hex[:6], "number": f"Q-{n:06d}", "client": client, "items": items,
             "vat_rate": str(rate_d.normalize()) if rate_d != rate_d.to_integral() else str(int(rate_d)),
             "currency": cur, "issued": issued.isoformat(), "valid_until": (issued + timedelta(days=days)).isoformat(),
             "status": "draft", "sent_on": "", "decided_on": "", "notes": str(notes).strip()[:500],
             "lang": "bg" if lang == "bg" else "en", "seller": dict(me), "file": "", "deal": str(deal or "")[:12],
             "invoice": "", "alerted": ""}
        data["quotes"].append(q)
        data["next"] = n + 1
        return dict(q)

    return _change(go)


def get(key: str) -> dict | None:
    """By id, by number ("Q-000003") or by the number alone ("3")."""
    key = str(key).strip().lstrip("№#").strip()
    items = load()["quotes"]
    hit = next((q for q in items if q["id"] == key or q["number"].lower() == key.lower()), None)
    if hit or not re.fullmatch(r"(?i)q?-?\d{1,6}", key):
        return hit
    n = int(re.sub(r"\D", "", key))
    return next((q for q in items if int(q["number"][2:]) == n), None)


def find(words: str) -> dict:
    """One quote: by id or number, else the only one whose client is named. Several -> ask for the number."""
    q = get(words)
    if q:
        return q
    hits = match(words)
    if not hits:
        raise ValueError("no quote matches that (see quotes_list)")
    open_ = [x for x in hits if x["status"] in ("draft", "sent")]
    if len(hits) > 1 and len(open_) != 1:
        raise ValueError("several quotes match: " + ", ".join(x["number"] for x in hits[:8]) + " - say the number")
    return open_[0] if len(hits) > 1 else hits[0]


def match(words: str) -> list[dict]:
    """Quotes whose client is named in the words, newest first: whole names first ("Acme Test" never picks "Acme
    Corp"), single words only when no whole name is there."""
    low = (words or "").lower()
    items = load()["quotes"]
    out = [q for q in items if re.search(r"(?<!\w)" + re.escape(q["client"]["name"].lower()) + r"(?!\w)", low)]
    if not out:
        terms = [t for t in re.findall(r"[\w]{3,}", low)
                 if t not in {"quote", "quotes", "quotation", "offer", "the", "for", "accepted", "declined", "sent"}]
        out = [q for q in items if any(t in q["client"]["name"].lower() for t in terms)]
    return sorted(out, key=lambda q: q["number"], reverse=True)


def _set(qid: str, **changes) -> dict | None:
    def go(data):
        for q in data["quotes"]:
            if q["id"] == qid:
                q.update(changes)
                return dict(q)
        return None

    return _change(go)


def set_file(qid: str, path: str) -> dict | None:
    return _set(qid, file=str(path))


def set_status(qid: str, status: str, today: date | None = None) -> dict:
    """draft / sent / declined. An accepted quote cannot change (its invoice exists)."""
    if status not in SETTABLE:
        raise ValueError("a quote can be marked draft, sent or declined (accepting it makes the invoice)")
    q = get(qid)
    if not q:
        raise ValueError("no such quote")
    if q["status"] == "accepted":
        raise ValueError(f"quote {q['number']} was accepted and invoiced (invoice no. {q['invoice']}) - void the "
                         "invoice instead")
    today = today or date.today()
    ch: dict = {"status": status}
    if status == "sent":
        ch["sent_on"] = q.get("sent_on") or today.isoformat()
    ch["decided_on"] = today.isoformat() if status == "declined" else ""
    return _set(q["id"], **ch)


def remove(qid: str) -> dict | None:
    """Delete a quote made by mistake. An accepted one stays (its invoice points to it)."""
    def go(data):
        q = next((x for x in data["quotes"] if x["id"] == qid), None)
        if q and q["status"] == "accepted":
            raise ValueError(f"quote {q['number']} was accepted and invoiced - it stays")
        if q:
            data["quotes"].remove(q)
        return q

    return _change(go)


def invoice_of(q: dict) -> dict | None:
    """The invoice already made from this quote (by an accept that stopped half way), if any. The invoice carries the
    quote's number in its first words from the moment it is numbered, so this is never missed."""
    return next((i for i in B.load()["invoices"] if i.get("status") != "void"
                 and (i.get("quote") == q["id"] or str(i.get("notes", "")).startswith(f"Quote {q['number']}."))), None)


def may_accept(q: dict) -> bool:
    """The role may accept THIS quote: quotes and invoices, and the deal too when one is linked."""
    from . import company, deals as D

    if not (company.can("quotes.write") and company.can("invoices.write")):
        return False
    return not (q.get("deal") and D.get(q["deal"]) and not company.can("deals.write"))


def check_accept(q: dict, made: dict | None = None) -> None:
    """Everything that must be true BEFORE the invoice number is used up (`made`: the invoice an earlier, unfinished
    accept already made - then only the linking is left)."""
    from . import company, deals as D

    company.require("quotes.write")
    company.require("invoices.write")
    if q["status"] == "accepted":
        raise ValueError(f"quote {q['number']} is already accepted (invoice no. {q['invoice']})")
    if q["status"] == "declined":
        raise ValueError(f"quote {q['number']} was declined - mark it sent first if the client changed their mind")
    if q.get("deal"):
        d = D.get(q["deal"])
        if d:
            company.require("deals.write")
            if d.get("invoice") and not (made and d["invoice"] == made["number"]):
                raise ValueError(f"the {d['client']} deal already has invoice no. {d['invoice']}")


def mark_accepted(qid: str, invoice_number: str, today: date | None = None) -> dict | None:
    """After the invoice is made: the quote is accepted and points to it (the deal is moved by the caller)."""
    return _set(qid, status="accepted", invoice=str(invoice_number), decided_on=(today or date.today()).isoformat())


# ---------------------------------------------------------------- words

def quote_line(q: dict, ids: bool = True, today: date | None = None) -> str:
    today = today or date.today()
    total = B.money(totals(q)[2], q["currency"], False)
    st = status_of(q, today)
    if st in ("draft", "sent"):
        state = f"{st}, valid until {B.day_text(date.fromisoformat(q['valid_until']), False, today)}"
    elif st == "accepted":
        state = f"accepted - invoice no. {q['invoice']}"
    elif st == "expired":
        state = f"expired on {q['valid_until']}"
    else:
        state = st
    return f"{q['number']} {q['client']['name']}: {total} - {state}" + (f"  [id {q['id']}]" if ids else "")


def list_text(ids: bool = True, today: date | None = None, status: str = "") -> str:
    today = today or date.today()
    items = sorted(load()["quotes"], key=lambda q: q["number"], reverse=True)
    if status:
        items = [q for q in items if status_of(q, today) == status]
    if not items:
        return (f"No {status} quotes." if status else
                "No quotes yet. Say e.g. \"make a quote for Acme: 10 hours of design at 60 EUR\".")
    open_ = [q for q in items if status_of(q, today) in ("draft", "sent")]
    t: dict[str, int] = {}
    for q in open_:
        t[q["currency"]] = t.get(q["currency"], 0) + totals(q)[2]
    head = (f"Open quotes: {len(open_)}, {B.totals_text(t, False)} in total." if open_ else "No open quotes.")
    return "\n".join([head] + ["• " + quote_line(q, ids, today) for q in items[:30]])


_UNIT = r"hours?|hrs?|h|days?|pcs|pieces?|units?|items?|pages?|months?|weeks?"
# a number in a sentence has no spaces inside ("logo 3 300" is two numbers, never 3300); a field may ("1 200")
_NUMX = r"\d{1,3}(?:[,.]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_NUMX_FIELD = r"\d{1,3}(?:[,.\u00a0 ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_CUR_W = r"(?:" + B._CUR_ALT + r")"
_PRICE = (r"(?:(?P<c1>" + _CUR_W + r")\s*)?(?P<price>" + _NUMX + r")(?:\s*(?P<c2>" + _CUR_W + r"))?")
_PER = r"(?:\s+(?:each|apiece|per\s+[a-z]+|an?\s+(?:hour|day|piece|unit|item|page))|\s*/\s*[a-z]+)?"
_QTY = r"(?P<qty>\d{1,3}(?:[,.]\d{3})+|\d+(?:[.,]\d+)?)"
# the only shapes a line may have; anything else is refused (the model takes over) - a wrong price is never guessed
_FORMS = [re.compile(r"(?i)^" + f + r"\s*$") for f in (
    _QTY + r"\s*[x×*]\s*(?P<desc>.+?)\s+(?:(?:at|@|à)\s+)?" + _PRICE + _PER,  # 3 x consulting 150
    _QTY + r"\s*(?P<unit>" + _UNIT + r")?\s+(?:of\s+)?(?P<desc>.+?)\s+(?:at|@|à)\s+" + _PRICE + _PER,  # 10 hours of design at 60
    r"(?P<desc>.+?)\s*:?\s+" + _QTY + r"\s*(?P<unit>" + _UNIT + r")\s+(?:at|@|à)\s+" + _PRICE + _PER,  # design 10 hours at 60
    r"(?P<desc>.+?)\s+" + _QTY + r"\s*[x×*]\s*" + _PRICE + _PER,  # hosting 12 x 10
    r"(?P<desc>.+?)\s*[-–:=]?\s+" + _PRICE,  # hosting 120 EUR / logo - 300  (WHOLE: checked by _WHOLE_BAD)
)]
_WHOLE = len(_FORMS) - 1
# the "description + one price" shape must not hide a quantity or a price in its description: "design 60 EUR x 10",
# "10 hours of design 60 EUR", a description ending in a word that leads to a price - those are asked, not guessed
# ... and no number standing on its own ("Phase 1 300", "logo 300 - 50", "logo €300 50": which one is the price?)
# - "3D", "v2" and "300x250" are words, they stay
_WHOLE_BAD = re.compile(r"(?i)(?<![\w])\d+(?:[.,]\d+)*(?![\w])|(?<![\w])" + _CUR_W + r"(?![\w])|[€$£]|"
                        r"(?<![\w])(?:x|×|\*|per|each|for|по|за)\s*$")
_PRICE_ONLY = re.compile(r"(?i)^\s*(?:(?P<c1>" + _CUR_W + r")\s*)?(?P<price>" + _NUMX_FIELD + r")(?:\s*(?P<c2>" + _CUR_W +
                         r"))?\s*$")


def price_cents(text: str, currency_ok: bool = True) -> tuple[int, str]:
    """A price typed in a field or a "|" cell -> (cents, currency word or ""). Strict: only a number (and a currency
    word when currency_ok), at most two decimals - "1O0" or "0.125" are refused, never read as 10 or 0.13."""
    m = _PRICE_ONLY.match(str(text))
    word = (m.group("c1") or m.group("c2") or "") if m else ""
    if not m or (word and not currency_ok):
        raise ValueError(f"the price '{text}' must be a number, e.g. 1200 or 1,200.50")
    if re.fullmatch(r"0[.,]\d{3,}", m.group("price").replace(" ", "")):
        raise ValueError(f"a price has at most two decimals: '{text}'")
    return B.cents(m.group("price")), word
_BAD_DESC = re.compile(r"(?i)(?<![\w])(?:at|à)(?![\w])|@|\(|\)|%")


def items_from(text: str) -> tuple[list[dict], str]:
    """'10 hours of design at 60 EUR, hosting 120 EUR' -> (items, currency); '' when no currency was said. Leva are
    converted to euro. STRICT: a line that is not exactly one of the known shapes raises ValueError, because a guessed
    price would end up on a quote and maybe an invoice ('at 60 EUR (incl. 2 revisions)', 'by 15.12' ...)."""
    parts = [x.strip(" .") for x in re.split(r"\n|;|,\s+|\s+plus\s+|\s+and\s+(?=\d)", str(text)) if x.strip(" .")]
    if not parts:
        raise ValueError("the quote needs at least one line")
    rows, curs = [], set()
    for part in parts:
        cells = [c.strip() for c in part.split("|")]
        unit = ""
        if len(cells) in (2, 3):
            desc, qty, price_txt = (cells[0], "1", cells[1]) if len(cells) == 2 else cells
            price, word = price_cents(price_txt)
        elif len(cells) == 1:
            m, form = next(((f.match(part), n) for n, f in enumerate(_FORMS) if f.match(part)), (None, -1))
            if m and form in (0, _WHOLE - 1, _WHOLE) and _WHOLE_BAD.search(m.group("desc")):
                m = None  # "3 x logo 1 500", "logo 300 - 50": which number is the price? asked, never guessed
            elif m and re.search(r"(?i)(?<![\w])" + _CUR_W + r"(?![\w])|[€$£]", m.group("desc")):
                m = None  # "10 hours of design 60 EUR at 2": a price inside the description
            if not m:
                raise ValueError(f"I could not read the line '{part}'. Use e.g. '10 hours of design at 60 EUR' or "
                                 "'Design | 10 | 60'.")
            g = m.groupdict()
            desc, qty, unit = g["desc"], g.get("qty") or "1", g.get("unit") or ""
            if re.fullmatch(r"0[.,]\d{3,}", g["price"]):
                raise ValueError(f"a price has at most two decimals: '{part}'")  # 0.125 is never rounded quietly
            price, word = B.cents(g["price"]), g.get("c1") or g.get("c2") or ""
        else:
            raise ValueError(f"I could not read the line '{part}'")
        desc = re.sub(r"\s+", " ", desc).strip(" -–:=,")
        if not re.search(r"[^\W\d_]", desc) or _BAD_DESC.search(desc):
            raise ValueError(f"I could not read the line '{part}'")
        if word:
            curs.add(B.currency_of(word))
        rows.append({"desc": (desc[:1].upper() + desc[1:] + (f" ({unit.lower()})" if unit else ""))[:200],
                     "qty": B.qty_of(qty), "price": price})
    if len(curs) > 1:
        raise ValueError("one currency per quote")
    cur = curs.pop() if curs else ""
    if cur == "BGN":  # leva said or typed: the quote is in euro
        for r in rows:
            r["price"] = B.euro_first(r["price"], "BGN")[0]
        cur = "EUR"
    return rows[:100], cur


# ---------------------------------------------------------------- reminders

def fire_due(now: datetime | None = None, toast: bool = True) -> list[str]:
    """A draft or sent quote: REMIND_DAYS before its valid-until date and once when it has expired (08:00-21:59)."""
    from . import reminders

    now = now or datetime.now()
    if not 8 <= now.hour < 22:
        return []
    today = now.date()
    fired = []
    with _lock:
        data, changed = load(strict=True), False
        for q in data["quotes"]:
            if q["status"] not in ("draft", "sent") or not q.get("valid_until"):
                continue
            until = date.fromisoformat(q["valid_until"])
            keys = set(filter(None, (q.get("alerted") or "").split("|")))
            who = f"quote {q['number']} for {q['client']['name']}"
            if until < today and f"x{until}" not in keys:
                keys.add(f"x{until}")
                keys.add(f"b{until}")
                fired.append(f"{who} expired on {until.isoformat()} - ask the client, or mark it declined")
            elif today <= until <= today + timedelta(days=REMIND_DAYS) and f"b{until}" not in keys:
                keys.add(f"b{until}")
                fired.append(f"{who} is valid until {B.day_text(until, False, today)} - a good moment to follow up")
            new = "|".join(sorted(keys))
            if new != (q.get("alerted") or ""):
                q["alerted"], changed = new, True
        if changed:
            _store(data)
    for text in fired:
        reminders.notify("Vaelon - quote", text, "reminder", toast)
    return fired


# ---------------------------------------------------------------- the PDF

def quote_pdf(q: dict, path: Path) -> None:
    """The quote as an A4 PDF: the invoice layout, titled "Quote", with the valid-until date."""
    B.invoice_pdf({**q, "due": q["valid_until"]}, path, kind="quote")


# ---------------------------------------------------------------- company mode: who may change what (and the journal)
from . import company as _co  # noqa: E402

new_quote = _co.guarded(new_quote, "quotes.write", "quote made",
                        lambda r, a, k: f"{r['number']} {r['client']['name']} {B.money(totals(r)[2], r['currency'])}")
set_status = _co.guarded(set_status, "quotes.write", "quote status", lambda r, a, k: f"{r['number']}: {r['status']}" if r else "")
set_file = _co.guarded(set_file, "quotes.write", "quote PDF", lambda r, a, k: r["number"] if r else "")
remove = _co.guarded(remove, "quotes.write", "quote deleted", lambda r, a, k: r["number"] if r else "")
mark_accepted = _co.guarded(mark_accepted, "quotes.write", "quote accepted",
                            lambda r, a, k: f"{r['number']} -> invoice {r['invoice']}" if r else "")
restore_all = _co.guarded(restore_all, "quotes.write", "undo", lambda r, a, k: "quotes")
