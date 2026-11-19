"""What the app's deals tab may read and do. The model's tools are in tools/money.py; both use deals.py."""
from __future__ import annotations

import re
from datetime import date

from . import bills as B
from . import deals as D


def _deal(d: dict, today: date) -> dict:
    out = {k: d.get(k) for k in ("id", "client", "title", "value", "currency", "stage", "close", "next_step", "next_date",
                                 "contact", "notes", "won_on", "lost_reason", "invoice", "updated")}
    out["chance"] = D.CHANCE[d["stage"]]
    out["late"] = d["stage"] in D.OPEN and bool(d.get("next_date")) and date.fromisoformat(d["next_date"]) < today
    out["stale"] = (d["stage"] in D.OPEN and not d.get("next_date")
                    and (today - date.fromisoformat(d["updated"])).days >= D.STALE_DAYS)
    return out


def overview(today: date | None = None) -> dict:
    from . import company

    company.require("deals.read")
    today = today or date.today()
    items = D.load()
    open_ = [d for d in items if d["stage"] in D.OPEN]
    total: dict[str, int] = {}
    expected: dict[str, int] = {}
    won: dict[str, int] = {}
    for d in open_:
        total[d["currency"]] = total.get(d["currency"], 0) + d["value"]
        expected[d["currency"]] = expected.get(d["currency"], 0) + D.weighted(d)
    year = str(today.year)
    won_n = lost_n = 0
    for d in items:
        if d["stage"] == "won" and d.get("won_on", "")[:4] == year:
            won[d["currency"]] = won.get(d["currency"], 0) + d["value"]
            won_n += 1
        elif d["stage"] == "lost" and d.get("updated", "")[:4] == year:
            lost_n += 1
    order = {s: n for n, s in enumerate(("negotiation", "proposal", "contacted", "lead", "won", "lost"))}
    rows = sorted(items, key=lambda d: (order[d["stage"]], -d["value"], d["client"].lower()))
    return {"today": today.isoformat(), "deals": [_deal(d, today) for d in rows], "stages": list(D.STAGES),
            "chance": D.CHANCE, "currencies": list(B.CURRENCIES),
            "totals": {"open": total, "expected": expected, "won_year": won, "won": won_n, "lost": lost_n,
                       "year": today.year, "count": len(open_)}}


def act(cfg, data: dict) -> tuple[bool, dict]:
    """add / update / note / delete / invoice."""
    from .registry_ctx import ctx_for
    from .security import undo

    action = data.get("action")
    before = D.snapshot()

    def done(label: str, **extra) -> tuple[bool, dict]:
        undo.push(label, lambda: D.restore_all(before))
        return True, {"ok": True, **extra}

    def day(field: str):
        v = str(data.get(field, "") or "").strip()
        if v and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            raise ValueError(f"{field} must look like 2026-11-25")
        return date.fromisoformat(v) if v else None

    try:
        if action == "add":
            value = str(data.get("value", "")).strip()
            d = D.add(str(data.get("client", "")), str(data.get("title", "")), B.cents(value) if value else 0,
                      str(data.get("currency") or "EUR").upper(), str(data.get("stage") or "lead"), day("close"),
                      str(data.get("next_step", "")), day("next_date"), str(data.get("contact", "")), str(data.get("note", "")))
            return done(f"add deal {d['client']}", deal=_deal(d, date.today()))
        if action in ("update", "note", "delete", "invoice"):
            d = D.get(str(data.get("id", "")))
            if not d:
                return False, {"ok": False, "error": "no such deal"}
            if action == "delete":
                D.remove(d["id"])
                return done(f"delete deal {d['client']}")
            if action == "note":
                text = str(data.get("text", "")).strip()
                if not text:
                    return False, {"ok": False, "error": "write the note first"}
                D.update(d["id"], note=text)
                return done(f"note on {d['client']}")
            if action == "invoice":
                from .tools.money import deal_invoice

                out = deal_invoice(ctx_for(cfg), d["id"])
                if out.startswith("ERROR"):
                    return False, {"ok": False, "error": out[7:]}
                m = re.search(r"created (.+?\.pdf)", out)
                from .bills_api import _with_size

                return True, _with_size({"ok": True, "path": m.group(1) if m else "", "text": out.split(". created")[0]})
            ch: dict = {}
            if "stage" in data:
                ch["stage"] = str(data["stage"])
            if "value" in data:
                ch["value"] = B.cents(str(data["value"])) if str(data["value"]).strip() else 0
            if "currency" in data:
                cur = str(data["currency"]).upper()
                if cur not in B.CURRENCIES:
                    raise ValueError("currency must be one of " + ", ".join(B.CURRENCIES))
                ch["currency"] = cur
            for k, n in (("client", 120), ("title", 200), ("next_step", 200), ("contact", 120), ("lost_reason", 200)):
                if k in data:
                    ch[k] = str(data[k]).strip()[:n]
            if ch.get("client") == "":
                return False, {"ok": False, "error": "a deal needs a client"}
            for k in ("close", "next_date"):
                if k in data:
                    v = day(k)
                    ch[k] = v.isoformat() if v else ""
            if not ch:
                return False, {"ok": False, "error": "nothing to change"}
            d = D.update(d["id"], **ch)
            return done(f"change deal {d['client']}", deal=_deal(d, date.today()))
    except (ValueError, TypeError) as e:
        D.restore_all(before)
        return False, {"ok": False, "error": str(e) or "bad value"}
    return False, {"ok": False, "error": "unknown action"}
