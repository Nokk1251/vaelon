"""What the app's Recurring and Reminders tabs may read and do (issue #44). The model's tools are in tools/money.py;
both use recurring.py and payreminders.py. Sending a reminder: the app asks first in the tab, every time; the
model's tool always shows a card."""
from __future__ import annotations

from datetime import date, datetime

from . import bills as B
from . import payreminders as P
from . import recurring as R
from .security.policy import PolicyError


def _plan(p: dict) -> dict:
    net, vat, total = B.invoice_totals({"items": p["items"], "vat_rate": p["vat_rate"]})
    return {"id": p["id"], "client": p["client"]["name"], "email": p["client"].get("email", ""), "every": p["every"],
            "day": p["day"], "next": p["next"], "active": bool(p["active"]), "currency": p["currency"], "net": net,
            "vat": vat, "total": total, "vat_rate": p["vat_rate"], "lines": len(p["items"]), "due_days": p["due_days"],
            "made": [m["number"] for m in p.get("made", [])][-6:], "error": p.get("error", ""), "lang": p.get("lang", "en"),
            "notes": p.get("notes", "")}


def _draft(d: dict, inv: dict | None, today: date) -> dict:
    late = (today - date.fromisoformat(inv["due"])).days if inv else 0
    return {"id": d["id"], "invoice": d["invoice"], "number": d["number"], "client": d["client"], "stage": d["stage"],
            "to": d["to"], "subject": d["subject"], "body": d["body"], "made": d["made"], "edited": bool(d.get("edited")),
            "total": B.invoice_totals(inv)[2] if inv else 0, "currency": inv["currency"] if inv else "EUR",
            "due": inv["due"] if inv else "", "late": late, "demo": bool(d.get("demo") or (inv or {}).get("demo"))}


def recurring_overview() -> dict:
    from . import company

    company.require("invoices.read")
    me = B.load()["me"]
    plans = sorted(R.load()["plans"], key=lambda p: (not p["active"], p["next"]))
    return {"today": date.today().isoformat(), "plans": [_plan(p) for p in plans], "has_business": bool(me.get("name")),
            "vat_rate": me.get("vat_rate") or ("20" if me.get("vat_id") else "0"), "currency": me.get("currency") or "EUR",
            "currencies": list(B.CURRENCIES), "may_write": company.can("invoices.write")}


def reminders_overview(cfg=None) -> dict:
    from . import company
    from .tools.comms import mail_ready
    from .config import Config

    company.require("invoices.read")
    today = date.today()
    invoices = {i["id"]: i for i in B.load()["invoices"]}
    drafts = [_draft(d, invoices.get(d["invoice"]), today) for d in P.open_drafts()]
    every_sent = sorted((d for d in P.load()["drafts"] if d["status"] == "sent"), key=lambda d: d.get("sent_on", ""))
    last_sent = {d["invoice"]: d for d in every_sent}  # the newest reminder that went out, per invoice
    sent = list(reversed(every_sent))[:10]
    have = {d["invoice"] for d in drafts}
    all_drafts = P.load()["drafts"]  # read once, not once per invoice
    overdue = [{"id": i["id"], "number": i["number"], "client": i["client"]["name"], "due": i["due"],
                "late": (today - date.fromisoformat(i["due"])).days, "total": B.invoice_totals(i)[2],
                "currency": i["currency"], "reminded": last_sent[i["id"]]["sent_on"] if i["id"] in last_sent else "",
                "stage": max([x["stage"] for x in all_drafts if x["invoice"] == i["id"] and x["status"] != "closed"]
                             or [0]), "sent_stage": last_sent[i["id"]]["stage"] if i["id"] in last_sent else 0}
               for i in invoices.values()
               if i["status"] == "unpaid" and date.fromisoformat(i["due"]) < today and i["id"] not in have]
    try:
        ready = mail_ready(cfg or Config.load())
    except Exception:
        ready = False
    return {"today": today.isoformat(), "settings": P.settings(), "drafts": drafts,
            "sent": [{"id": d["id"], "number": d["number"], "client": d["client"], "to": d["to"], "sent_on": d["sent_on"],
                      "stage": d["stage"]} for d in sent],
            "overdue": sorted(overdue, key=lambda x: -x["late"]), "mail_ready": ready,
            "may_write": company.can("invoices.write"), "may_send": company.can("mail.send") and company.can("invoices.write")}


def recurring_act(cfg, data: dict) -> tuple[bool, dict]:
    """add / pause / resume / delete / run (make the invoices that are due now)."""
    from .quotes import price_cents
    from .security import undo

    action = data.get("action")
    try:
        if action == "add":
            client = data.get("client") if isinstance(data.get("client"), dict) else {}
            rows = data.get("items") if isinstance(data.get("items"), list) else []
            items = []
            for r in rows[:100]:  # the fields as typed - never joined into one text and split again
                if not isinstance(r, dict) or not str(r.get("desc", "")).strip():
                    continue
                price, _ = price_cents(str(r.get("price", "")), currency_ok=False)
                items.append({"desc": " ".join(str(r["desc"]).split())[:200], "qty": B.qty_of(r.get("qty") or 1),
                              "price": price})
            if not items:
                return False, {"ok": False, "error": "add at least one line with a description and a price"}
            day = str(data.get("day", "")).strip()
            start = str(data.get("start", "")).strip()
            before = R.snapshot()
            p = R.new_plan({"name": client.get("name", ""), "email": client.get("email", ""),
                            "address": client.get("address", ""), "vat_id": client.get("vat_id", ""),
                            "company_id": client.get("company_id", "")}, items,
                           str(data.get("every", "monthly")), int(day) if day.isdigit() else None,
                           str(data.get("vat_rate", "")).strip() or None, str(data.get("due_days", "14")),
                           str(data.get("currency", "")), str(data.get("notes", "")),
                           "bg" if data.get("lang") == "bg" else "en", date.fromisoformat(start) if start else None)
            undo.push(f"recurring invoice {p['client']['name']}", lambda: R.restore_all(before))
            return True, {"ok": True, "plan": _plan(p)}
        if action == "run":
            from . import company

            company.require("invoices.write")
            said = R.run_due(cfg, datetime.now(), toast=False, asked=True)
            return True, {"ok": True, "said": said}
        p = R.get(str(data.get("id", "")))
        if not p:
            return False, {"ok": False, "error": "no such plan"}
        before = R.snapshot()
        if action in ("pause", "resume"):
            out = R.set_active(p["id"], action == "resume")
            undo.push(f"recurring invoice {p['client']['name']} {action}", lambda: R.restore_all(before))
            return True, {"ok": True, "plan": _plan(out)}
        if action == "delete":
            R.remove(p["id"])
            undo.push(f"delete recurring invoice {p['client']['name']}", lambda: R.restore_all(before))
            return True, {"ok": True}
        return False, {"ok": False, "error": "unknown action"}
    except (ValueError, TypeError, RuntimeError, PolicyError) as e:  # company.Denied goes on: the server answers 403
        return False, {"ok": False, "error": str(e)}


def reminders_act(cfg, data: dict) -> tuple[bool, dict]:
    """settings / draft (for one overdue invoice) / edit / dismiss / send (the tab asked the user first)."""
    from .security import undo

    action = data.get("action")
    try:
        if action == "settings":
            before = P.snapshot()
            s = P.set_settings(data.get("on"), data.get("first"), data.get("second"))
            undo.push("payment reminder settings", lambda: P.restore_all(before))
            return True, {"ok": True, "settings": s}
        if action == "draft":
            before = P.snapshot()
            d = P.draft_now(str(data.get("invoice", "")))
            undo.push(f"payment reminder for invoice {d['number']}", lambda: P.restore_all(before))
            return True, {"ok": True, "id": d["id"]}
        d = next((x for x in P.load()["drafts"] if x["id"] == str(data.get("id", ""))), None)
        if not d:
            return False, {"ok": False, "error": "no such draft"}
        if action == "edit":
            before = P.snapshot()
            P.edit(d["id"], data.get("to"), data.get("subject"), data.get("body"))
            undo.push(f"edit payment reminder {d['number']}", lambda: P.restore_all(before))
            return True, {"ok": True}
        if action == "dismiss":
            before = P.snapshot()
            P.dismiss(d["id"])
            undo.push(f"dismiss payment reminder {d['number']}", lambda: P.restore_all(before))
            return True, {"ok": True}
        if action == "send":
            # the tab showed the address, subject and text and the user pressed Send in that confirmation; `confirm`
            # must name exactly what was shown, so a changed draft (another window, the model) is never sent unseen
            seen = data.get("confirm") if isinstance(data.get("confirm"), dict) else {}
            out = P.send(cfg, d["id"], expect=(seen.get("to"), seen.get("subject"), seen.get("body")))
            return True, {"ok": True, "to": out["to"], "number": out["number"]}
        return False, {"ok": False, "error": "unknown action"}
    except Exception as e:  # a role refusal (company.Denied) goes on: the server answers 403
        from . import company

        if isinstance(e, company.Denied):
            raise
        if not isinstance(e, (ValueError, TypeError, RuntimeError, PolicyError, OSError)):
            raise
        return False, {"ok": False, "error": str(e)[:300]}
