"""Payment reminders to clients (issue #44): when an invoice the user issued is overdue, Vaelon writes a polite
reminder as a DRAFT - first friendly, then firmer - and tells the user. Vaelon NEVER sends it by itself: the user
checks it and sends it with one click (it asks every time) or copies the text into their own mail.

    Money > Reminders     "which payment reminders are ready?"  (the model's tools payment_reminders / _send)

The text is made only from the user's own data: the invoice (number, date, total, due date, days late) and the
payment details of the business profile. Nothing from outside goes in. The address is the client's email on the
invoice, else a saved contact with exactly the client's name (owner only), else empty (the user fills it in).

An invoice marked paid (by hand, or by a bank CSV import) or voided closes its drafts: nothing is drafted or sent for
it any more. Sending checks that again at the last moment.

Stored ENCRYPTED in ~/.vaelon/payreminders.enc (per company in company mode): {settings: {on, first, second},
drafts: [{id, invoice, number, client, stage 1|2, to, subject, body, made, status draft|sent|dismissed|closed|replaced,
sent_on, edited}]}.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from . import bills as B
from .security import vault

FILE = "payreminders.enc"
DEFAULTS = {"on": True, "first": 7, "second": 21}  # days after the due date
GAP = 7  # the firmer one comes at least this many days after the friendly one was drafted
OPEN = ("draft",)
_lock = threading.Lock()
_send_lock = threading.Lock()  # one send at a time: a double click never sends the same reminder twice


# ---------------------------------------------------------------- storage

def _path() -> Path:
    from . import company

    return company.data_dir() / FILE


def _empty() -> dict:
    return {"settings": dict(DEFAULTS), "drafts": []}


def load(strict: bool = False) -> dict:
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
    out = _empty()
    if isinstance(data.get("settings"), dict):
        out["settings"].update({k: v for k, v in data["settings"].items() if k in DEFAULTS})
    if isinstance(data.get("drafts"), list):
        out["drafts"] = [d for d in data["drafts"] if isinstance(d, dict)]
    return out


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
    """Undo: drafts and settings go back - but a reminder that was SENT stays sent (an email cannot be taken back)."""
    with _lock:
        now = load(strict=True)
        data = json.loads(json.dumps(data))
        sent = {d["id"]: d for d in now["drafts"] if d.get("status") == "sent"}
        have = {d["id"] for d in data.get("drafts", [])}
        data["drafts"] = [sent.get(d["id"], d) for d in data.get("drafts", [])] + [
            d for d in sent.values() if d["id"] not in have]
        _store({"settings": {**DEFAULTS, **data.get("settings", {})}, "drafts": data["drafts"]})


# ---------------------------------------------------------------- settings

def settings() -> dict:
    return dict(load()["settings"])


def set_settings(on=None, first=None, second=None) -> dict:
    def go(data):
        s = data["settings"]
        if on is not None:
            s["on"] = bool(on) if isinstance(on, bool) else str(on).lower() in ("1", "true", "yes", "on")
        for k, v in (("first", first), ("second", second)):
            if v is not None:
                if not str(v).strip().isdigit() or not 1 <= int(v) <= 365:
                    raise ValueError("days after the due date must be 1-365")
                s[k] = int(v)
        if s["second"] <= s["first"]:
            raise ValueError("the firmer reminder must come later than the friendly one")
        return dict(s)

    return _change(go)


# ---------------------------------------------------------------- the text (only the user's own data)

def _addr(inv: dict) -> str:
    """The client's email: on the invoice, else a saved contact with exactly that name - the owner's personal
    contacts, so only in the personal space (never copied into a company's drafts)."""
    from . import company
    from .tools.comms import _EMAIL, _contacts

    mail = _visible(inv["client"].get("email") or "").strip()
    if mail and _EMAIL.match(mail):
        return mail
    u = company.user()
    if not u or u.get("role") != "owner" or company.workspace() != company.PERSONAL:
        return ""
    name = inv["client"]["name"].strip().lower()
    try:
        hit = next((v for k, v in _contacts().items() if k.strip().lower() == name), None)
    except Exception:
        hit = None
    mail = str((hit or {}).get("email") or "").strip()
    return mail if mail and _EMAIL.match(mail) else ""


def _visible(s: str) -> str:
    """Without the characters that hide or reorder text (bidi marks, zero-width, controls): what the user approves on
    the card is exactly what the client reads."""
    from .security.confirm import _HIDDEN

    return _HIDDEN.sub("", str(s or ""))


def _clean(s: str, n: int) -> str:
    return re.sub(r"\s+", " ", _visible(s)).strip()[:n]


def compose(inv: dict, stage: int, today: date | None = None) -> tuple[str, str]:
    """(subject, body) of the reminder, in the invoice's language. Made from the invoice and the business profile."""
    today = today or date.today()
    me = B.load()["me"]
    seller = inv.get("seller") or {}
    bg = inv.get("lang") == "bg"
    total = B.money(B.invoice_totals(inv)[2], inv["currency"], bg)
    due, issued = date.fromisoformat(inv["due"]), date.fromisoformat(inv["issued"])
    late = max(1, (today - due).days)
    fmt = (lambda d: f"{d.day:02d}.{d.month:02d}.{d.year}") if bg else (lambda d: d.isoformat())
    client = inv["client"]
    hello = _clean(client.get("person") or client.get("name"), 80)
    name = _clean(me.get("name") or seller.get("name"), 120)
    bank = _clean(me.get("bank") or seller.get("bank"), 300)
    person = _clean(me.get("person") or seller.get("person"), 80)
    contact = " | ".join(x for x in (_clean(me.get("email"), 120), _clean(me.get("phone"), 40)) if x)
    no = inv["number"]
    if bg:
        pay = ("\n\nДанни за плащане:\n" + name + ("\n" + bank if bank else "") + f"\nОснование: фактура № {no}")
        sign = "\n\nПоздрави,\n" + "\n".join(x for x in (person, name, contact) if x)
        if stage == 1:
            subject = f"Напомняне: фактура № {no}"
            body = (f"Здравейте, {hello},\n\nПриятелско напомняне, че фактура № {no} от {fmt(issued)} за {total} "
                    f"беше с падеж {fmt(due)}. Възможно е да е останала незабелязана. Ако вече сте платили, "
                    "благодарим ви и моля, не обръщайте внимание на това писмо." + pay + sign)
        else:
            subject = f"Второ напомняне: фактура № {no} е просрочена с {late} дни"
            body = (f"Здравейте, {hello},\n\nВсе още не сме получили плащане по фактура № {no} от {fmt(issued)} за "
                    f"{total}, с падеж {fmt(due)} (преди {late} дни). Моля, платете в следващите 7 дни или ни кажете, "
                    "ако има проблем с фактурата." + pay + sign)
    else:
        pay = ("\n\nPayment details:\n" + name + ("\n" + bank if bank else "") + f"\nReference: invoice {no}")
        sign = "\n\nKind regards,\n" + "\n".join(x for x in (person, name, contact) if x)
        if stage == 1:
            subject = f"Friendly reminder: invoice {no}"
            body = (f"Hello {hello},\n\nThis is a friendly reminder that invoice no. {no} of {fmt(issued)} for {total} "
                    f"was due on {fmt(due)}. Perhaps it slipped through. If you have already paid, thank you, and please "
                    "ignore this message." + pay + sign)
        else:
            subject = f"Second reminder: invoice {no} is {late} days overdue"
            body = (f"Hello {hello},\n\nWe have not yet received payment for invoice no. {no} of {fmt(issued)} for "
                    f"{total}, which was due on {fmt(due)} ({late} days ago). Please pay within the next 7 days, or let "
                    "us know if there is a problem with the invoice." + pay + sign)
    return subject, body


# ---------------------------------------------------------------- drafts

def _invoice_open(inv: dict | None) -> bool:
    return bool(inv) and inv["status"] == "unpaid"


def _close_settled(data: dict, invoices: dict) -> bool:
    """Drafts of invoices that were paid, voided or removed are closed. Returns whether anything changed."""
    changed = False
    for d in data["drafts"]:
        if d["status"] in OPEN and not _invoice_open(invoices.get(d["invoice"])):
            d["status"], changed = "closed", True
    return changed


def _new(inv: dict, stage: int, today: date) -> dict:
    subject, body = compose(inv, stage, today)
    return {"id": uuid.uuid4().hex[:6], "invoice": inv["id"], "number": inv["number"], "client": inv["client"]["name"],
            "stage": stage, "to": _addr(inv), "subject": subject, "body": body, "made": today.isoformat(),
            "status": "draft", "sent_on": "", "edited": False, **({"demo": True} if inv.get("demo") else {})}


def _due_stage(inv: dict, drafts: list[dict], s: dict, today: date) -> int:
    """Which reminder this invoice needs now (0 = none)."""
    late = (today - date.fromisoformat(inv["due"])).days
    mine = [d for d in drafts if d["invoice"] == inv["id"] and d["status"] != "closed"]
    has1 = [d for d in mine if d["stage"] == 1]
    if any(d["stage"] == 2 for d in mine):
        return 0
    if not has1:
        return 1 if late >= s["first"] else 0
    if late >= s["second"] and min(date.fromisoformat(d["made"]) for d in has1) <= today - timedelta(days=GAP):
        return 2
    return 0


def fire_due(now: datetime | None = None, toast: bool = True) -> list[str]:
    """Draft the reminders that are due (08:00-21:59) and close the drafts of settled invoices. Nothing is sent."""
    from . import reminders

    now = now or datetime.now()
    today = now.date()
    invoices = {i["id"]: i for i in B.load()["invoices"]}
    fired = []
    with _lock:
        data = load(strict=True)
        changed = _close_settled(data, invoices)
        s = data["settings"]
        if s.get("on") and 8 <= now.hour < 22:
            for inv in invoices.values():
                if not _invoice_open(inv) or date.fromisoformat(inv["due"]) >= today:
                    continue
                stage = _due_stage(inv, data["drafts"], s, today)
                if not stage:
                    continue
                for d in data["drafts"]:  # the friendly one was never sent: the firmer one takes its place
                    if d["invoice"] == inv["id"] and d["status"] in OPEN:
                        d["status"] = "replaced"
                data["drafts"].append(_new(inv, stage, today))
                changed = True
                late = (today - date.fromisoformat(inv["due"])).days
                fired.append(f"{'a firmer' if stage == 2 else 'a friendly'} payment reminder for invoice no. "
                             f"{inv['number']} ({inv['client']['name']}, {late} days late) is ready to check in Money > "
                             "Reminders. It was NOT sent")
        old = (today - timedelta(days=400)).isoformat()
        keep = [d for d in data["drafts"] if d["status"] in OPEN or d.get("sent_on", d["made"]) >= old or d["made"] >= old]
        if len(keep) != len(data["drafts"]):
            data["drafts"], changed = keep, True
        if changed:
            _store(data)
    from .recurring import shown_notices

    for text in shown_notices(fired):
        reminders.notify("Vaelon - payment reminder", text, "reminder", toast)
    return fired


def draft_now(invoice: str, today: date | None = None) -> dict:
    """Draft a reminder for one overdue invoice now (the user asked): friendly first, firmer if a friendly one was
    already sent or drafted. An open draft of that invoice is returned as it is."""
    today = today or date.today()
    inv = B.find_invoice(str(invoice))
    if not inv:
        raise ValueError("no such invoice")
    if inv["status"] != "unpaid":
        raise ValueError(f"invoice no. {inv['number']} is {inv['status']} - no reminder needed")
    if date.fromisoformat(inv["due"]) >= today:
        raise ValueError(f"invoice no. {inv['number']} is not overdue yet (due {inv['due']})")

    def go(data):
        mine = [d for d in data["drafts"] if d["invoice"] == inv["id"] and d["status"] != "closed"]
        open_ = next((d for d in mine if d["status"] in OPEN), None)
        if open_:
            return dict(open_)
        d = _new(inv, 2 if any(x["stage"] == 1 for x in mine) else 1, today)
        data["drafts"].append(d)
        return dict(d)

    return _change(go)


def get(key: str) -> dict | None:
    key = str(key or "").strip()
    drafts = load()["drafts"]
    hit = next((d for d in drafts if d["id"] == key), None)
    if hit:
        return hit
    num = key.lstrip("№#").strip()
    if num.isdigit():  # the invoice number: its open draft
        return next((d for d in drafts if d["status"] in OPEN and d["number"].isdigit() and int(d["number"]) == int(num)), None)
    return None


def open_drafts() -> list[dict]:
    """The drafts waiting for the user (settled invoices left out even before the thread has closed them)."""
    invoices = {i["id"]: i for i in B.load()["invoices"]}
    return [d for d in load()["drafts"] if d["status"] in OPEN and _invoice_open(invoices.get(d["invoice"]))]


def edit(did: str, to=None, subject=None, body=None) -> dict:
    """The user's own changes to a draft (address, subject, text)."""
    from .tools.comms import _EMAIL

    def go(data):
        d = next((x for x in data["drafts"] if x["id"] == did), None)
        if not d or d["status"] not in OPEN:
            raise ValueError("no such draft (it may be sent or closed)")
        if to is not None:
            t = _visible(to).strip()
            if t and not _EMAIL.match(t):
                raise ValueError("that is not an email address")
            d["to"] = t
        if subject is not None:
            sub = _clean(subject, 200)
            if not sub:
                raise ValueError("the subject cannot be empty")
            d["subject"] = sub
        if body is not None:
            text = _visible(str(body).replace("\r\n", "\n")).strip()
            if not text:
                raise ValueError("the text cannot be empty")
            d["body"] = text[:6000]
        d["edited"] = True
        return dict(d)

    return _change(go)


def dismiss(did: str) -> dict | None:
    def go(data):
        d = next((x for x in data["drafts"] if x["id"] == did), None)
        if not d or d["status"] not in OPEN:
            return None
        d["status"] = "dismissed"
        return dict(d)

    return _change(go)


def check_send(d: dict) -> dict:
    """Everything that must hold before a reminder goes out. Returns the invoice."""
    from .tools.comms import _EMAIL

    if not d or d.get("status") not in OPEN:
        raise ValueError("this reminder is not a draft any more (sent, dismissed or closed)")
    inv = B.find_invoice(d["invoice"])
    if not _invoice_open(inv):
        raise ValueError(f"invoice no. {d['number']} is not unpaid any more - the reminder is not needed")
    if inv.get("demo") or d.get("demo"):
        raise ValueError("this is demo data - nothing is sent for it (copy the text to see it)")
    if not d.get("to") or not _EMAIL.match(d["to"]):
        raise ValueError("add the client's email address to the draft first")
    return inv


def send(cfg, did: str, today: date | None = None, expect=None) -> dict:
    """Send ONE draft by email. Callers ask the user first, every time (the app's confirmation, the tool's card), and
    pass what was shown as `expect`: the card text (the tool) or (to, subject, body) (the app). It is compared under the
    send lock, so a draft changed in between is never sent unseen."""
    from . import company
    from .tools import comms

    company.require("mail.send")
    company.require("invoices.write")
    with _send_lock:
        d = next((x for x in load()["drafts"] if x["id"] == did), None)
        check_send(d)
        if expect is None:
            raise ValueError("a reminder is sent only after the user saw exactly what goes out")
        now = card(d) if isinstance(expect, str) else (d["to"], d["subject"], d["body"])
        if now != (expect if isinstance(expect, str) else tuple(expect)):
            raise ValueError("the draft changed since it was shown - look at it again")
        if not comms.mail_ready(cfg):
            raise RuntimeError("email is not set up: Settings > Phone and email (or copy the text into your own mail)")
        comms.deliver(cfg, d["to"], d["subject"], d["body"])

        def go(data):
            for x in data["drafts"]:
                if x["id"] == did:
                    x["status"], x["sent_on"] = "sent", (today or date.today()).isoformat()
                    return dict(x)
            return dict(d)  # the file changed under us: the mail is out anyway

        try:
            out = _change(go)
        except Exception:
            out = {**d, "status": "sent"}  # sent: never report a sent mail as not sent
        if company.enabled():
            from . import journal

            try:
                journal.add("payment reminder sent", f"invoice no. {d['number']} to {d['to']}")
            except Exception:
                pass
        return out


def draft_line(d: dict) -> str:
    to = d["to"] or "no address yet"
    return (f"{'firmer' if d['stage'] == 2 else 'friendly'} reminder for invoice no. {d['number']} ({d['client']}) to "
            f"{to}, drafted {d['made']}  [id {d['id']}]")


def card(d: dict) -> str:
    """The approval card for sending: who gets it and exactly what they get."""
    return f"EMAIL a payment reminder to {d['to'] or '(no address)'}\n  Subject: {d['subject']}\n\n{d['body']}"


# ---------------------------------------------------------------- company mode: who may change what (and the journal)
from . import company as _co  # noqa: E402

set_settings = _co.guarded(set_settings, "invoices.write", "payment reminder settings",
                           lambda r, a, k: f"on={r['on']} first={r['first']} second={r['second']}")
draft_now = _co.guarded(draft_now, "invoices.write", "payment reminder drafted", lambda r, a, k: f"invoice no. {r['number']}")
edit = _co.guarded(edit, "invoices.write", "payment reminder edited", lambda r, a, k: f"invoice no. {r['number']}")
dismiss = _co.guarded(dismiss, "invoices.write", "payment reminder dismissed",
                      lambda r, a, k: f"invoice no. {r['number']}" if r else "")
restore_all = _co.guarded(restore_all, "invoices.write", "undo", lambda r, a, k: "payment reminders")
