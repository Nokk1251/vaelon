"""Demo data: made-up bills, a budget, deals, invoices, business details and a few calendar entries, so the Money
panel and the calendar can be tried at once. Everything added here is marked (`"demo": true`) and
`remove()` takes away ONLY what is marked - the owner's own entries are never touched.

    vaelon demo load      /  "load demo data"
    vaelon demo remove    /  "remove the demo data"

Demo invoices are numbered "DEMO-000001" ..., OUTSIDE the real series, so removing them never leaves a gap in the
unbroken invoice numbering. A backup of the files it changes is taken first (~/.vaelon/backup-before-demo-<time>).
All names, companies and amounts are invented.
"""
from __future__ import annotations

import shutil
import time
import uuid
from datetime import date, datetime, timedelta

from . import agenda, bills as B, budget as BU, config, deals as D

FILES = (B.FILE, BU.FILE, D.FILE, agenda.FILE)


def present() -> bool:
    return any(x.get("demo") for x in B.load()["bills"]) or any(x.get("demo") for x in D.load())


def _backup() -> str:
    from . import company

    folder = config.HOME / f"backup-before-demo-{time.strftime('%Y%m%d-%H%M%S')}"
    folder.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        src = (config.HOME if f == agenda.FILE else company.data_dir()) / f  # the calendar is personal
        if src.exists():
            shutil.copy2(src, folder / f)
    return str(folder)


def load(today: date | None = None) -> dict:
    """Add the demo set (once). Returns what was added."""
    from . import company

    company.require("workspaces.manage")
    if present():
        raise ValueError("the demo data is already there - remove it first")
    t = today or date.today()
    backup = _backup()
    first = t.replace(day=1)
    last_month = (first - timedelta(days=1)).replace(day=1)

    # bills: open, overdue, repeating, paid last month
    def bill(vendor, amount, due, category="", repeat="", paid_on=None, number=""):
        b = B.add_bill(vendor, amount, "EUR", due, category, number, "", repeat, 3)
        if paid_on:
            B.mark_paid(b["id"], paid_on)
        B.update_bill(b["id"], demo=True)

    bill("Northwind Power", 5240, t + timedelta(days=4), "electricity", "monthly", number="4400123987")
    bill("City Water Co", 1890, t - timedelta(days=2), "water")
    bill("Apartment rent", 65000, t + timedelta(days=12), "rent", "monthly")
    bill("Fibrelink", 2999, last_month + timedelta(days=24), "internet & phone", paid_on=last_month + timedelta(days=22))
    bill("Car insurance", 24000, t + timedelta(days=40), "insurance", "yearly")
    for b in B.load()["bills"]:  # the estimate a paid repeating bill may have made is demo too
        if b.get("estimate") and not b.get("demo"):
            B.update_bill(b["id"], demo=True)

    # budget: limits, this month's money in and out, a little of last month
    def go_budget(data):
        data["currency"] = data.get("currency") or "EUR"
        added = []
        for cat, v in (("groceries", 40000), ("eating out", 12000), ("transport", 15000), ("total", 180000)):
            if cat not in data["limits"]:  # a limit the owner set stays the owner's
                data["limits"][cat] = v
                added.append(cat)
        data["demo_limits"] = added
    BU._change(go_budget)
    rows = [("income", 240000, "Salary", first + timedelta(days=0)), ("expense", 6230, "Supermarket", first + timedelta(days=1)),
            ("expense", 4810, "Grocery store", first + timedelta(days=3)), ("expense", 450, "coffee", t),
            ("expense", 1480, "lunch with colleagues", t - timedelta(days=1)), ("expense", 7000, "fuel", first + timedelta(days=2)),
            ("expense", 1240, "pharmacy", first + timedelta(days=4)), ("expense", 1800, "cinema", first + timedelta(days=5)),
            ("expense", 3990, "birthday present", first + timedelta(days=6)),
            ("income", 45000, "Logo design fee", first + timedelta(days=7)),
            ("income", 240000, "Salary", last_month), ("expense", 9120, "Supermarket", last_month + timedelta(days=5)),
            ("expense", 6500, "fuel", last_month + timedelta(days=9))]
    ids = []
    for kind, amount, note, on in rows:
        if on > t:
            on = t
        ids.append(BU.add(kind, amount, "EUR", "", note, on)["id"])

    def tag(data):
        for e in data["entries"]:
            if e["id"] in ids:
                e["demo"] = True
    BU._change(tag)

    # business details (only if none are set) and two invoices outside the real numbering
    def go_bills(data):
        if not data["me"].get("name"):
            data["me"] = {"name": "Demo Studio Ltd", "address": "1 Example Street, Example City", "company_id": "000000000",
                          "person": "Alex Demo", "bank": "Bank: (demo - enter your own details in My business)",
                          "vat_rate": "20", "currency": "EUR", "demo": True}
        seller = dict(data["me"])
        for n, (client, desc, price, paid, issued) in enumerate((
                ("Initech Ltd", "Hosting and support - 12 months", 120000, False, t - timedelta(days=4)),
                ("Sample Cafe", "Menu and business cards", 45000, True, t - timedelta(days=20))), 1):
            data["invoices"].append({"id": uuid.uuid4().hex[:6], "number": f"DEMO-{n:06d}", "client": {"name": client, "address": "",
                                     "company_id": "", "vat_id": "", "person": "", "email": ""},
                                     "items": [{"desc": desc, "qty": "1", "price": price}], "vat_rate": seller.get("vat_rate", "20"),
                                     "currency": "EUR", "issued": issued.isoformat(), "due": (issued + timedelta(days=14)).isoformat(),
                                     "status": "paid" if paid else "unpaid", "paid_on": (issued + timedelta(days=6)).isoformat() if paid else "",
                                     "notes": "", "lang": "en", "seller": seller, "file": "", "demo": True})
    B._change(go_bills)

    # deals
    for client, title, value, stage, extra in (
            ("Acme Ltd", "Website", 500000, "proposal", {"next_step": "send the proposal", "next_date": t + timedelta(days=1)}),
            ("Globex", "Mobile app", 1200000, "negotiation", {"close": t + timedelta(days=20), "note": "they liked the demo"}),
            ("Sample Shop", "Logo and business cards", 80000, "lead", {}),
            ("Initech Ltd", "Hosting", 120000, "won", {})):
        d = D.add(client, title, value, "EUR", stage, extra.get("close"), extra.get("next_step", ""), extra.get("next_date"),
                  "", extra.get("note", ""))
        D.update(d["id"], demo=True, **({"invoice": "DEMO-000001"} if stage == "won" else {}))

    # calendar
    for title, when, all_day, repeat, remind in (
            ("Meeting with Acme Ltd", datetime.combine(t + timedelta(days=1), datetime.min.time()).replace(hour=10), False, "", 15),
            ("Birthday: Mum (demo)", datetime.combine(t + timedelta(days=9), datetime.min.time()), True, "yearly", 900),
            ("Yoga", datetime.combine(t + timedelta(days=2), datetime.min.time()).replace(hour=18, minute=30), False, "weekly", 15)):
        ev = agenda.add(title, when, 60, all_day, "", "", repeat, remind)
        agenda.update(ev["id"], demo=True)
    return {"backup": backup, "bills": 5, "entries": len(ids), "deals": 4, "invoices": 2, "events": 3}


def remove() -> dict:
    """Take away everything marked demo - and nothing else."""
    from . import company

    company.require("workspaces.manage")
    counts = {}

    def go_bills(data):
        n0, i0 = len(data["bills"]), len(data["invoices"])
        data["bills"] = [b for b in data["bills"] if not b.get("demo")]
        data["invoices"] = [i for i in data["invoices"] if not i.get("demo")]
        if data["me"].get("demo"):
            data["me"] = {}
        counts["bills"], counts["invoices"] = n0 - len(data["bills"]), i0 - len(data["invoices"])
    B._change(go_bills)

    def go_budget(data):
        n0 = len(data["entries"])
        data["entries"] = [e for e in data["entries"] if not e.get("demo")]
        for cat in data.pop("demo_limits", []):
            data["limits"].pop(cat, None)
        counts["entries"] = n0 - len(data["entries"])
    BU._change(go_budget)
    every = D.load(strict=True)  # strict: an unreadable file must never be "restored" as an empty one
    keep = [d for d in every if not d.get("demo")]
    counts["deals"] = len(every) - len(keep)
    if counts["deals"]:
        D.restore_all(keep)
    evs = agenda.load(strict=True)
    counts["events"] = sum(1 for e in evs if e.get("demo"))
    for e in evs:
        if e.get("demo"):
            agenda.remove(e["id"])
    return counts


def text(counts: dict, loaded: bool, bg: bool) -> str:
    if loaded:
        return ("Заредих демо данни: 5 сметки, бюджет с лимити и " + str(counts["entries"]) + " движения, 4 сделки, 2 фактури "
                "(DEMO-…, извън истинската ти номерация) и 3 събития в календара. Отвори ¤ Money и ▦. "
                "Махат се с „махни демо данните“ - твоите записи не се пипат." if bg else
                "Demo data loaded: 5 bills, a budget with limits and " + str(counts["entries"]) + " entries, 4 deals, 2 invoices "
                "(DEMO-..., outside your real numbering) and 3 calendar events. Open ¤ Money and ▦. "
                "\"Remove the demo data\" takes them away - your own entries are never touched.")
    total = sum(counts.values())
    return (f"Махнах демо данните ({total} записа). Твоите си стоят." if bg else
            f"Demo data removed ({total} items). Your own entries are untouched.")
