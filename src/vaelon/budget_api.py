"""What the app's budget tab may read and do. The model's tools are in tools/money.py; both use budget.py."""
from __future__ import annotations

import re
from datetime import date

from . import bills as B
from . import budget as BU
from .security.policy import PolicyError


def overview(month: str = "") -> dict:
    """One month: income, spending per category against the limits, the entries and the paid bills, in the budget
    currency (cents)."""
    from . import company

    company.require("budget.read")
    try:
        first = date.fromisoformat(month + "-01") if re.fullmatch(r"\d{4}-\d{2}", month or "") else date.today().replace(day=1)
    except ValueError:
        first = date.today().replace(day=1)
    m = BU.month(first)
    cats = sorted(set(m["by_category"]) | {c for c in m["limits"] if c != "total"},
                  key=lambda c: (-m["by_category"].get(c, 0), c))
    return {
        "month": f"{first:%Y-%m}", "label": BU.month_label(first, False), "currency": m["currency"],
        "income": m["income"], "spent": m["spent"], "left": m["left"],
        "total_limit": m["limits"].get("total"),
        "rows": [{"category": c, "spent": m["by_category"].get(c, 0), "limit": m["limits"].get(c)} for c in cats],
        "apart": m["apart"],
        "entries": [{k: e[k] for k in ("id", "kind", "amount", "currency", "category", "note", "date")} for e in m["entries"]],
        "bills": [{"id": b["id"], "vendor": b["vendor"], "amount": b["amount"], "currency": b["currency"],
                   "category": b["category"], "date": b["paid_on"]} for b in m["bills"]],
        "categories": list(BU.CATEGORY_NAMES), "currencies": list(B.CURRENCIES),
    }


def act(data: dict, cfg=None) -> tuple[bool, dict]:
    """add (expense / income) / delete / limit / currency."""
    from .security import undo

    action = data.get("action")
    before = BU.snapshot()

    def done(label: str, **extra) -> tuple[bool, dict]:
        undo.push(label, lambda: BU.restore_all(before))
        return True, {"ok": True, **extra}

    try:
        if action == "add":
            on = str(data.get("date", "")).strip()
            if on and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", on):
                return False, {"ok": False, "error": "the date must look like 2026-11-25"}
            kind = "income" if data.get("kind") == "income" else "expense"
            e = BU.add(kind, B.cents(str(data.get("amount", ""))), str(data.get("currency", "")), str(data.get("category", "")),
                       str(data.get("note", "")), date.fromisoformat(on) if on else None)
            return done(f"add {kind}", entry=e, warning=BU.warning(e["category"], False, on=e.get("date")).strip() if kind == "expense" else "")
        if action == "delete":
            if not BU.remove(str(data.get("id", ""))):
                return False, {"ok": False, "error": "no such entry"}
            return done("delete entry")
        if action == "limit":
            amount = data.get("amount")
            BU.set_limit(str(data.get("category", "")), None if amount in (None, "") else B.cents(str(amount)))
            return done("set limit")
        if action == "import":  # a statement the app uploaded (output folder / Attachments): preview first
            from pathlib import Path

            from . import bankcsv
            from .security.policy import resolve_path
            from .tools.create import out_dir

            p = resolve_path(str(data.get("path", "")), [str(out_dir(cfg))])
            if p.suffix.lower() not in (".csv", ".txt") or not p.is_file():
                return False, {"ok": False, "error": "choose the statement as a .csv file"}
            s, text = bankcsv.import_file(Path(p), apply=not data.get("preview"), bg=False)
            return True, {"ok": True, "summary": {k: v for k, v in s.items()}, "text": text}
        if action == "currency":
            BU.set_currency(str(data.get("currency", "")))
            return done("budget currency")
    except (ValueError, TypeError) as e:
        return False, {"ok": False, "error": str(e) or "bad value"}
    except PolicyError:
        return False, {"ok": False, "error": "only a file you attached in the app can be imported"}
    except OSError as e:
        return False, {"ok": False, "error": f"could not read the file: {e.strerror or e}"}
    return False, {"ok": False, "error": "unknown action"}
