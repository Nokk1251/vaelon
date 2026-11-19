"""What the app's bills panel may read and do. The model's tools live in tools/money.py; both use bills.py.
Nothing here pays anything: "paid" only marks a bill in the list."""
from __future__ import annotations

import re
from datetime import date

from . import bills as B


def _bill(b: dict, today: date) -> dict:
    out = {k: b.get(k) for k in ("id", "vendor", "amount", "currency", "due", "category", "number", "notes", "status",
                                 "paid_on", "repeat", "remind", "estimate")}
    out["overdue"] = b["status"] == "unpaid" and bool(b["due"]) and date.fromisoformat(b["due"]) < today
    out["label"] = B.bill_line(b, False, ids=False, today=today)
    return out


def _invoice(i: dict, today: date) -> dict:
    net, vat, total = B.invoice_totals(i)
    return {"id": i["id"], "number": i["number"], "client": i["client"]["name"], "issued": i["issued"], "due": i["due"],
            "status": i["status"], "paid_on": i["paid_on"], "currency": i["currency"], "net": net, "vat": vat,
            "total": total, "vat_rate": i["vat_rate"], "file": i.get("file", ""),
            "overdue": i["status"] == "unpaid" and date.fromisoformat(i["due"]) < today}


def overview(today: date | None = None) -> dict:
    from . import company

    if not (company.can("bills.read") or company.can("invoices.read")):
        company.require("bills.read")
    today = today or date.today()
    data = B.load()
    if not company.can("bills.read"):
        data["bills"] = []
    if not company.can("invoices.read"):
        data["invoices"] = []
    bills = sorted(data["bills"], key=lambda b: (b["status"] != "unpaid", b["due"] == "", b["due"] if b["status"] == "unpaid"
                                                 else "", b.get("paid_on", "")), reverse=False)
    paid = [b for b in data["bills"] if b["status"] == "paid"]
    paid.sort(key=lambda b: b.get("paid_on", ""), reverse=True)
    open_ = [b for b in data["bills"] if b["status"] == "unpaid"]
    year = [b for b in paid if b.get("paid_on", "")[:4] == str(today.year)]
    by_cat: dict[str, dict[str, int]] = {}
    for b in year:
        slot = by_cat.setdefault(b["category"], {})
        slot[b["currency"]] = slot.get(b["currency"], 0) + b["amount"]
    return {
        "today": today.isoformat(),
        "unpaid": [_bill(b, today) for b in bills if b["status"] == "unpaid"],
        "paid": [_bill(b, today) for b in paid[:200]],
        "invoices": [_invoice(i, today) for i in sorted(data["invoices"], key=lambda i: i["number"], reverse=True)],
        "me": dict(data["me"]),
        "next": f"{int(data.get('next') or 1):010d}",
        "totals": {"unpaid": B.totals(open_), "overdue": sum(1 for b in open_ if b["due"] and date.fromisoformat(b["due"]) < today),
                   "paid_year": B.totals(year), "by_category": by_cat, "year": today.year},
        "categories": list(B.CATEGORY_NAMES), "currencies": list(B.CURRENCIES),
    }


def _with_size(answer: dict) -> dict:
    """The app's file card shows the size of a file it can open."""
    from pathlib import Path

    p = Path(answer.get("path") or "")
    if answer.get("path") and p.is_file():
        answer["kb"] = max(1, p.stat().st_size // 1024)
    return answer


def act(cfg, data: dict) -> tuple[bool, dict]:
    """add / paid / unpaid / delete / invoice / invoice_paid / invoice_unpaid / invoice_void / profile / export."""
    from .registry_ctx import ctx_for
    from .security import undo

    action = data.get("action")
    before = B.snapshot()

    def done(label: str, **extra) -> tuple[bool, dict]:
        undo.push(label, lambda: B.restore_all(before))
        return True, {"ok": True, **extra}

    try:
        if action == "add":
            due = str(data.get("due", "")).strip()
            if due and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
                return False, {"ok": False, "error": "the due date must look like 2026-11-25"}
            cur = str(data.get("currency") or "EUR").upper()
            remind = data.get("remind", 3)
            b = B.add_bill(str(data.get("vendor", "")), B.cents(str(data.get("amount", ""))), cur,
                           date.fromisoformat(due) if due else None, str(data.get("category", "")),
                           str(data.get("number", "")), str(data.get("notes", "")), B.repeat_of(str(data.get("repeat", ""))),
                           None if remind is None else int(remind))
            return done(f"add bill {b['vendor']}", bill=b)
        if action in ("paid", "unpaid", "delete"):
            b = B.get_bill(str(data.get("id", "")))
            if not b:
                return False, {"ok": False, "error": "no such bill"}
            if action == "paid":
                on = str(data.get("date", "")).strip()
                B.mark_paid(b["id"], date.fromisoformat(on) if on else None)
            elif action == "unpaid":
                B.mark_unpaid(b["id"])
            else:
                B.delete_bill(b["id"])
            return done(f"{action} {b['vendor']}")
        if action == "invoice":
            from .tools.money import make_invoice

            client = data.get("client") if isinstance(data.get("client"), dict) else {}
            rows = data.get("items") if isinstance(data.get("items"), list) else []
            items = []
            for r in rows[:100]:
                if not isinstance(r, dict) or not str(r.get("desc", "")).strip():
                    continue
                items.append(B.parse_items(f"{r.get('desc')} | {r.get('qty') or 1} | {r.get('price')}")[0])
            if not items:
                return False, {"ok": False, "error": "add at least one line with a description and a price"}
            days = data.get("due_days", 14)
            inv, msg = make_invoice(ctx_for(cfg), client, items, str(data.get("vat_rate", "")).strip() or None,
                                    int(days) if str(days).isdigit() else 14, str(data.get("currency", "")),
                                    str(data.get("notes", "")), "en" if data.get("lang") == "en" else "bg")
            return True, _with_size({"ok": True, "invoice": _invoice(inv, date.today()), "path": inv.get("file", "")})
        if action in ("invoice_paid", "invoice_unpaid", "invoice_void"):
            inv = B.find_invoice(str(data.get("id", "")))
            if not inv:
                return False, {"ok": False, "error": "no such invoice"}
            if action == "invoice_void":
                if inv["status"] == "void":
                    return False, {"ok": False, "error": "it is already void"}
                from .tools.money import invoice_void

                out = invoice_void(ctx_for(cfg), inv["id"])
                m = re.search(r"created (.+?\.pdf)", out)
                return True, _with_size({"ok": True, "path": m.group(1) if m else ""})
            if inv["status"] == "void":
                return False, {"ok": False, "error": "a void invoice cannot be paid"}
            B.update_invoice(inv["id"], status="paid" if action == "invoice_paid" else "unpaid",
                             paid_on=date.today().isoformat() if action == "invoice_paid" else "")
            return done(f"invoice {inv['number']} {action.split('_')[1]}")
        if action == "profile":
            fields = data.get("fields") if isinstance(data.get("fields"), dict) else {}
            allowed = set(B.PROFILE_FIELDS) | {"vat_rate", "currency", "next"}
            bad = [k for k in fields if k not in allowed]
            if bad:
                return False, {"ok": False, "error": f"unknown field: {bad[0]}"}
            fields = {k: v for k, v in fields.items() if not (k == "next" and str(v).lstrip("0") == str(B.load().get("next", 1)))}
            me = B.set_profile(**fields)
            return done("change business details", me=me)
        if action == "export":
            from .tools.money import money_export

            out = money_export(ctx_for(cfg), str(data.get("period", "")) or "this year")
            m = re.search(r"created (.+?\.xlsx)", out)
            return (True, _with_size({"ok": True, "path": m.group(1)})) if m else (False, {"ok": False, "error": out})
    except (ValueError, TypeError) as e:
        B.restore_all(before)
        return False, {"ok": False, "error": str(e) or "bad value"}
    return False, {"ok": False, "error": "unknown action"}
