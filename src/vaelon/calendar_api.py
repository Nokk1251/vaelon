"""What the app's calendar panel may read and do. The model's tools live in tools/planner.py; both use agenda.py."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from . import agenda


def _event(start: datetime, e: dict) -> dict:
    return {"id": e["id"], "title": e["title"], "start": agenda.iso(start), "minutes": e.get("minutes", 60),
            "all_day": bool(e.get("all_day")), "place": e.get("place", ""), "notes": e.get("notes", ""),
            "repeat": e.get("repeat", ""), "remind": e.get("remind")}


def days(frm: str = "", count: str = "14") -> dict:
    """{"days": [{"date", "label", "events": [...]}]} for `count` days from `frm` (default today). Empty days included."""
    try:
        first = date.fromisoformat(frm) if frm else date.today()
    except ValueError:
        first = date.today()
    try:
        n = min(62, max(1, int(count)))
    except ValueError:
        n = 14
    start = datetime.combine(first, datetime.min.time())
    rows = agenda.between(start, start + timedelta(days=n))
    out = []
    for k in range(n):
        d = first + timedelta(days=k)
        lo, hi = datetime.combine(d, datetime.min.time()), datetime.combine(d, datetime.min.time()) + timedelta(days=1)
        evs = [_event(s, e) for s, e in rows if s < hi and s + timedelta(minutes=e.get("minutes", 60)) > lo]
        out.append({"date": d.isoformat(), "label": agenda.day_label(d, False), "weekday": d.weekday(), "events": evs})
    return {"from": first.isoformat(), "days": out, "total": len(agenda.load())}


def act(cfg, data: dict) -> tuple[bool, dict]:
    """add / cancel / skip / export. Returns (ok, answer)."""
    from .tools import planner

    action = data.get("action")
    try:
        if action == "add":
            d, t = str(data.get("date", "")), str(data.get("time", "")).strip()
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) or (t and not re.fullmatch(r"\d{1,2}:\d{2}", t)):
                return False, {"ok": False, "error": "give a date (and a time like 09:30)"}
            minutes = data.get("minutes")
            duration = "all day" if not t else (f"{int(minutes)} min" if isinstance(minutes, int) and minutes > 0 else "")
            remind = data.get("remind")
            remind_text = "no" if remind is None and "remind" in data else ("" if remind is None else str(int(remind)))
            ev, clashes = planner.schedule(str(data.get("title", "")), f"{d} {t}" if t else d, duration,
                                           str(data.get("place", "")), str(data.get("notes", "")), remind_text,
                                           str(data.get("repeat", "")))
            return True, {"ok": True, "event": ev, "clashes": [{"title": e["title"], "start": agenda.iso(s)} for s, e in clashes]}
        if action in ("cancel", "skip"):
            ev = agenda.get(str(data.get("id", "")))
            if not ev:
                return False, {"ok": False, "error": "no such event"}
            if action == "skip":
                when = str(data.get("start", ""))
                if not ev.get("repeat") or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", when):
                    return False, {"ok": False, "error": "only one date of a repeating event can be skipped"}
                agenda.update(ev["id"], skip=(ev.get("skip") or []) + [when])
            else:
                agenda.remove(ev["id"])
            from .security import undo

            undo.push(f"{action} {ev['title']}", lambda: agenda.restore(ev))
            return True, {"ok": True}
        if action == "export":
            from .registry_ctx import ctx_for

            out = planner.calendar_export(ctx_for(cfg))
            m = re.search(r"created (.+?\.ics)", out)
            return (True, {"ok": True, "path": m.group(1)}) if m else (False, {"ok": False, "error": out})
    except ValueError as e:
        return False, {"ok": False, "error": str(e)}
    return False, {"ok": False, "error": "unknown action"}
