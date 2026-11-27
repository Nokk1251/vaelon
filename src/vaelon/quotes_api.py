"""What the app's quotes tab may read and do (issue #43). The model's tools are in tools/money.py; both use quotes.py.
Accepting a quote makes an invoice: the app asks first (in the tab), the model's tool always shows a card."""
from __future__ import annotations

from datetime import date

from . import bills as B
from . import quotes as Q
from .security.policy import PolicyError


def _quote(q: dict, today: date, deals: dict) -> dict:
    net, vat, total = Q.totals(q)
    d = deals.get(q.get("deal") or "")
    return {"id": q["id"], "number": q["number"], "client": q["client"]["name"], "issued": q["issued"],
            "valid_until": q["valid_until"], "status": Q.status_of(q, today), "currency": q["currency"], "net": net,
            "vat": vat, "total": total, "vat_rate": q["vat_rate"], "file": q.get("file", ""), "invoice": q.get("invoice", ""),
            "deal": q.get("deal", ""), "deal_label": f"{d['client']}{' - ' + d['title'] if d.get('title') else ''}" if d else "",
            "lines": len(q["items"]), "sent_on": q.get("sent_on", ""), "lang": q.get("lang", "en"),
            "may_accept": Q.may_accept(q)}


def overview(today: date | None = None) -> dict:
    from . import company, deals as D

    company.require("quotes.read")
    today = today or date.today()
    data = Q.load()
    deals = {d["id"]: d for d in D.load()} if company.can("deals.read") else {}
    items = sorted(data["quotes"], key=lambda q: q["number"], reverse=True)
    open_: dict[str, int] = {}
    for q in items:
        if Q.status_of(q, today) in ("draft", "sent"):
            open_[q["currency"]] = open_.get(q["currency"], 0) + Q.totals(q)[2]
    me = B.load()["me"]
    return {"today": today.isoformat(), "quotes": [_quote(q, today, deals) for q in items],
            "next": f"Q-{int(data.get('next') or 1):06d}", "open": open_, "has_business": bool(me.get("name")),
            "vat_rate": me.get("vat_rate") or ("20" if me.get("vat_id") else "0"), "currency": me.get("currency") or "EUR",
            "currencies": list(B.CURRENCIES),
            "deals": [{"id": d["id"], "label": f"{d['client']}{' - ' + d['title'] if d.get('title') else ''}",
                       "currency": d["currency"]} for d in deals.values() if d["stage"] in D.OPEN],
            "may_write": company.can("quotes.write"),
            "may_accept": company.can("quotes.write") and company.can("invoices.write")}


def act(cfg, data: dict) -> tuple[bool, dict]:
    """add / status / delete / accept."""
    from .bills_api import _invoice, _with_size
    from .registry_ctx import ctx_for
    from .security import undo
    from .tools.money import accept_quote, make_quote

    action = data.get("action")
    try:
        if action == "add":
            client = data.get("client") if isinstance(data.get("client"), dict) else {}
            rows = data.get("items") if isinstance(data.get("items"), list) else []
            items = []
            for r in rows[:100]:  # the fields as typed - never joined into one text and split again
                if not isinstance(r, dict) or not str(r.get("desc", "")).strip():
                    continue
                price, _ = Q.price_cents(str(r.get("price", "")), currency_ok=False)  # strict: "1O0", "0.125" refused
                items.append({"desc": " ".join(str(r["desc"]).split())[:200], "qty": B.qty_of(r.get("qty") or 1),
                              "price": price})
            if not items:
                return False, {"ok": False, "error": "add at least one line with a description and a price"}
            days = str(data.get("valid_days", 30))
            q, _ = make_quote(ctx_for(cfg), client, items, str(data.get("vat_rate", "")).strip() or None,
                              int(days) if days.isdigit() else 30, str(data.get("currency", "")), str(data.get("notes", "")),
                              "bg" if data.get("lang") == "bg" else "en", str(data.get("deal", "") or ""))
            return True, _with_size({"ok": True, "quote": _quote(q, date.today(), {}), "path": q.get("file", "")})
        q = Q.get(str(data.get("id", "")))
        if not q:
            return False, {"ok": False, "error": "no such quote"}
        if action == "status":
            before = Q.snapshot()
            out = Q.set_status(q["id"], str(data.get("status", "")))
            undo.push(f"quote {q['number']} {out['status']}", lambda: Q.restore_all(before))
            return True, {"ok": True}
        if action == "delete":
            before = Q.snapshot()
            Q.remove(q["id"])
            undo.push(f"delete quote {q['number']}", lambda: Q.restore_all(before))
            return True, {"ok": True}
        if action == "accept":
            q2, inv, _ = accept_quote(ctx_for(cfg), q["id"])
            return True, _with_size({"ok": True, "invoice": _invoice(inv, date.today()), "path": inv.get("file", ""),
                                     "number": inv["number"]})
        return False, {"ok": False, "error": "unknown action"}
    except (ValueError, TypeError, RuntimeError, PolicyError) as e:  # company.Denied goes on: the server answers 403
        return False, {"ok": False, "error": str(e)}
