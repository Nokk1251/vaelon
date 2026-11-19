"""Reminders and scheduled tasks as tools (the clear cases - "remind me in 10 minutes to ..." - are handled
directly by reminders.from_request without the model)."""
from __future__ import annotations

import time

from .. import reminders, scheduler
from ..security.policy import Risk
from .registry import tool


@tool("remind", "Set a reminder: a notification at a given time. `when` examples: 'in 20 minutes', 'at 17:30', "
                "'tomorrow at 9', '2026-12-24 18:00'.",
      {"when": "when to remind", "text": "what to remind about"}, group="planner")
def remind(ctx, when, text):
    ts, _rest = reminders.parse_when(str(when))
    if ts is None:
        return "ERROR: I could not understand the time. Use e.g. 'in 20 minutes', 'at 17:30', 'tomorrow at 9'."
    if ts < time.time() - 5:
        return "ERROR: that time is in the past"
    item = reminders.add(ts, str(text))
    return f"reminder {item['id']} set for {reminders.describe(ts)}: {item['text']}"


@tool("reminders_list", "List the reminders that are waiting", {}, group="planner")
def reminders_list(ctx):
    items = sorted(reminders.load(), key=lambda i: i["when"])
    return "\n".join(f"{i['id']}  {reminders.describe(i['when'])}  {i['text']}" for i in items) or "no reminders"


@tool("reminder_cancel", "Cancel a reminder by its id (see reminders_list)", {"id": "reminder id"}, group="planner")
def reminder_cancel(ctx, id):
    return "cancelled" if reminders.cancel(str(id).strip()) else "ERROR: no reminder with that id"


@tool("schedule_task", "Run a request again and again by itself: every day at a time (daily='08:00') OR every N "
                       "minutes. Unattended runs can never do dangerous actions; the result arrives as a notice.",
      {"prompt": "the request to run", "?daily": "HH:MM", "?every_minutes": "number of minutes"},
      risk=Risk.REVERSIBLE, group="planner",
      escalate=lambda a: True,  # it runs later with nobody watching: the user always sees and approves the request
      summary=lambda a: f"schedule '{a.get('prompt')}' ({a.get('daily') or str(a.get('every_minutes')) + ' min'})")
def schedule_task(ctx, prompt, daily="", every_minutes=""):
    try:
        every = int(float(every_minutes)) if str(every_minutes).strip() else None
        if every is not None and every < 5:
            return "ERROR: the shortest interval is 5 minutes"
        job = scheduler.add(str(prompt), every_minutes=every, daily=str(daily).strip() or None)
    except ValueError as e:
        return f"ERROR: {e}"
    return f"scheduled task {job['id']}: {job['prompt']} ({'daily at ' + job['daily'] if job['daily'] else f'every {every} minutes'})"


@tool("scheduled_list", "List the scheduled (recurring) tasks", {}, group="planner")
def scheduled_list(ctx):
    return "\n".join(f"{j['id']}  {'daily ' + j['daily'] if j.get('daily') else 'every ' + str(j.get('every_minutes')) + ' min'}"
                     f"  {j['prompt']}" for j in scheduler.load()) or "no scheduled tasks"


@tool("schedule_cancel", "Remove a scheduled task by its id (see scheduled_list)", {"id": "task id"},
      risk=Risk.REVERSIBLE, group="planner", summary=lambda a: f"remove scheduled task {a.get('id')}")
def schedule_cancel(ctx, id):
    return "removed" if scheduler.remove(str(id).strip()) else "ERROR: no scheduled task with that id"


# ---------------------------------------------------------------- the calendar (vaelon/agenda.py)
import re as _re
from datetime import datetime as _dt, timedelta as _td

from .. import agenda as _ag

_REPEAT_WORDS = (("daily", r"daily|every day|всеки ден|ежедневно"), ("weekly", r"weekly|every week|всяка седмица|ежеседмично"),
                 ("monthly", r"monthly|every month|всеки месец|ежемесечно"), ("yearly", r"yearly|every year|annually|всяка година|ежегодно"))


def _repeat_of(text: str) -> str:
    low = str(text or "").lower()
    if low in _ag.REPEATS:
        return low
    return next((r for r, rx in _REPEAT_WORDS if _re.search(rx, low)), "")


def _remind_of(text, default):
    """'15' / '1 hour' / '1 day' / 'no' -> minutes before (None = no reminder)."""
    low = str(text if text is not None else "").lower().strip()
    if low == "":
        return default
    if _re.search(r"^(no|none|off|never|0?\s*без|не|няма)\b|без напомн", low):
        return None
    m = _re.search(r"(\d+(?:[.,]\d+)?)\s*(d|day|days|ден|дни|дена)\b", low)
    if m:
        return round(float(m.group(1).replace(",", ".")) * 1440)
    return _ag.minutes_of(low)[0] if _re.search(r"\d", low) else default


def has_time(text: str) -> bool:
    """Was a time of day given (not just a day)? Without one an appointment becomes an all-day event."""
    return bool(reminders.AT_RX.search(text) or reminders.IN_RX.search(text) or _re.search(r"\d{4}-\d{2}-\d{2}[ T]\d{1,2}:\d{2}", text))


def schedule(title: str, when: str, duration="", place="", notes="", remind="", repeat="", undo_push=True) -> tuple[dict, list]:
    """Put an event in the calendar. Returns (event, clashing occurrences). Raises ValueError with a readable reason."""
    ts, _rest = reminders.parse_when(str(when))
    if ts is None:
        raise ValueError("I could not understand the date/time. Use e.g. 'Friday at 10', '20.11 at 15:00', 'tomorrow at 9'.")
    start = _dt.fromtimestamp(ts).replace(second=0, microsecond=0)
    minutes, all_day = _ag.minutes_of(duration)
    if not all_day and not has_time(str(when)) and not str(duration).strip():
        all_day = True  # "birthday on 20 November": the whole day
    if start < _dt.now() - _td(minutes=1) and not _repeat_of(repeat):
        raise ValueError("that time is in the past")
    ev = _ag.add(title, start, minutes, all_day, place, notes, _repeat_of(repeat), _remind_of(remind, None if all_day else 15))
    if undo_push:
        from ..security import undo

        undo.push(f"add event {ev['title']}", lambda: _ag.remove(ev["id"]))
    return ev, ([] if all_day else _ag.clashes(start, minutes, ignore=ev["id"]))


def describe_event(ev: dict, bg: bool = False) -> str:
    s = _ag.parse_iso(ev["start"])
    label = _ag.day_label(s.date(), bg)
    if label in ("Днес", "Утре", "Today", "Tomorrow"):
        label += f" ({s:%d.%m})"  # the weekday labels already carry the date
    when = (("цял ден" if bg else "all day") if ev["all_day"]
            else f"{s:%H:%M}-{s + _td(minutes=ev['minutes']):%H:%M}")
    rem = "" if ev["remind"] is None else (f", напомням {ev['remind']} мин преди" if bg else f", reminder {ev['remind']} min before")
    return f"{ev['title']} - {label}, {when}{rem}"


def clash_note(clashes, bg=False) -> str:
    if not clashes:
        return ""
    names = "; ".join(f"{s:%H:%M} {e['title']}" for s, e in clashes[:3])
    return (" Внимание: застъпва се с " if bg else " Note: it overlaps ") + names + "."


@tool("event_add", "Put an appointment/meeting/birthday in the calendar. `when`: 'Friday at 10', '20.11 at 15:00', "
      "'tomorrow at 9', '24 December' (no time = all day). Repeats: daily, weekly, monthly, yearly.",
      {"title": "what it is", "when": "date and time", "?duration": "e.g. '90 min', '2h', 'all day' (default 1 hour)",
       "?place": "where", "?notes": "details", "?remind": "minutes before, e.g. '15', '1 hour', '1 day', or 'no'",
       "?repeat": "daily / weekly / monthly / yearly"},
      risk=Risk.REVERSIBLE, group="planner")
def event_add(ctx, title, when, duration="", place="", notes="", remind="", repeat=""):
    ev, clashes = schedule(title, when, duration, place, notes, remind, repeat)
    return f"added [id {ev['id']}]: {describe_event(ev)}.{clash_note(clashes)}"


@tool("agenda", "What is in the calendar: 'today', 'tomorrow', 'this week', 'next week', 'this month' or a date "
      "(default: the next 7 days)", {"?period": "which days"}, group="planner")
def agenda(ctx, period=""):
    frm, to = _ag.span(str(period))
    from .registry import outside_shown

    outside_shown(ctx, [e for _, e in _ag.between(frm, to)])
    return _ag.agenda_text(frm, to, bg=ctx.extra.get("lang") == "bg")


@tool("event_find", "Find calendar events by words in the title, place or notes", {"query": "words to look for"}, group="planner")
def event_find(ctx, query):
    hits = _ag.find(str(query))
    from .registry import outside_shown

    outside_shown(ctx, [e for _, e in hits[:20]])
    return "\n".join(_ag.line(s, e, False) + f"  {s:%d.%m.%Y}" for s, e in hits[:20]) or "no matching events"


@tool("event_move", "Move a calendar event to another time (see agenda / event_find for the id)",
      {"id": "event id", "when": "new date and time", "?duration": "new length, if it changes"},
      risk=Risk.REVERSIBLE, group="planner")
def event_move(ctx, id, when, duration=""):
    from ..security import undo

    ev = _ag.get(str(id).strip())
    if not ev:
        return "ERROR: no event with that id"
    ts, _ = reminders.parse_when(str(when))
    if ts is None:
        return "ERROR: I could not understand the new time"
    before = dict(ev)
    new_start = _dt.fromtimestamp(ts).replace(second=0, microsecond=0)
    if not has_time(str(when)):  # "move it to Friday": same time of day
        old = _ag.parse_iso(ev["start"])
        new_start = new_start.replace(hour=old.hour, minute=old.minute)
    changes = {"start": _ag.iso(new_start), "alerted": ""}
    if str(duration).strip():
        changes["minutes"], changes["all_day"] = _ag.minutes_of(duration)
    ev = _ag.update(ev["id"], **changes)
    undo.push(f"move event {ev['title']}", lambda: _ag.restore(before))
    return f"moved: {describe_event(ev)}.{clash_note(_ag.clashes(new_start, ev['minutes'], ignore=ev['id']))}"


@tool("event_cancel", "Remove a calendar event (a repeating one entirely, or only on one date with `only_on`)",
      {"id": "event id", "?only_on": "for a repeating event: the one date to skip, e.g. '20.11'"},
      risk=Risk.REVERSIBLE, summary=lambda a: f"CANCEL calendar event {a.get('id')}", group="planner")
def event_cancel(ctx, id, only_on=""):
    from ..security import undo

    ev = _ag.get(str(id).strip())
    if not ev:
        return "ERROR: no event with that id"
    before = dict(ev)
    if str(only_on).strip() and ev.get("repeat"):
        ts, _ = reminders.parse_when(str(only_on))
        if ts is None:
            return "ERROR: I could not understand the date"
        d = _dt.fromtimestamp(ts).date()
        start = _ag.parse_iso(ev["start"])
        occ = _ag.occurrences(ev, _dt.combine(d, start.time()) - _td(minutes=1), _dt.combine(d, start.time()) + _td(days=1))
        if not occ:
            return "ERROR: it does not happen on that date"
        _ag.update(ev["id"], skip=(ev.get("skip") or []) + [_ag.iso(occ[0])])
        undo.push(f"skip {ev['title']}", lambda: _ag.restore(before))
        return f"skipped {ev['title']} on {occ[0]:%d.%m.%Y}; the other dates stay"
    _ag.remove(ev["id"])
    undo.push(f"cancel {ev['title']}", lambda: _ag.restore(before))
    return f"cancelled: {ev['title']}"


@tool("calendar_export", "Save the calendar as an .ics file (opens in Google Calendar, Outlook, phones)",
      {"?period": "only these days, e.g. 'this month' (default: everything)"}, risk=Risk.REVERSIBLE, group="planner")
def calendar_export(ctx, period=""):
    from .create import _save

    events = _ag.load()
    if str(period).strip():
        frm, to = _ag.span(str(period))
        keep = {e["id"] for _, e in _ag.between(frm, to)}
        events = [e for e in events if e["id"] in keep]
    if not events:
        return "the calendar has no events for that"
    body = _ag.to_ics(events)
    return _save(ctx, "Vaelon calendar", ".ics", lambda p: p.write_text(body, "utf-8", newline=""))


@tool("calendar_import", "Add the events of an .ics calendar file (e.g. exported from Google or Outlook)",
      {"path": "the .ics file"}, risk=Risk.REVERSIBLE, untrusted=True, group="planner")
def calendar_import(ctx, path):
    from ..security import undo
    from ..security.injection import fence
    from ..security.policy import resolve_path

    p = resolve_path(str(path), ctx.cfg.allowed_roots)
    if p.suffix.lower() != ".ics" or not p.is_file():
        return "ERROR: give an .ics file"
    if p.stat().st_size > 5_000_000:
        return "ERROR: the file is too large"
    found = _ag.from_ics(p.read_text("utf-8", errors="replace"))
    have = {(e["title"], e["start"]) for e in _ag.load()}
    added, ids, again, simplified = [], [], 0, 0
    try:
        for f in found[:2000]:
            if (f["title"], _ag.iso(f["start"])) in have:  # the same file imported twice: no duplicates
                again += 1
                continue
            note = f["notes"] + ("\n(repeat rule simplified on import - check it)" if f.get("simplified") else "")
            e = _ag.add(f["title"], f["start"], f["minutes"], f["all_day"], f["place"], note.strip(), f["repeat"],
                        None if f["all_day"] else 15)
            e = _ag.update(e["id"], src="import") or e  # its words came from the file: see registry.outside_shown
            if f.get("skip") and f["repeat"]:
                e = _ag.update(e["id"], skip=sorted(set(f["skip"])))
            simplified += bool(f.get("simplified"))
            ids.append(e["id"])
            added.append(e)
    finally:  # even when one entry breaks halfway, what was added can be taken back
        if ids:
            undo.push(f"import {p.name}", lambda: [_ag.remove(i) for i in ids])
    names = "\n".join(f"- {e['title']} ({_ag.parse_iso(e['start']):%d.%m.%Y %H:%M})" for e in added[:15])
    extra = (f"; {again} already in the calendar" if again else "") + \
        (f"; {simplified} repeat rules could not be followed exactly and were imported once (marked)" if simplified else "")
    return fence(f"imported {len(added)} events{extra}" + (f":\n{names}" if names else ""), f"calendar:{p.name}")[0]


@tool("study_plan", "Make a study plan for an exam and put every session in the calendar: the topics spread over the "
      "days left, the last day a mock exam. Call it once you know the topics.",
      {"subject": "the subject, e.g. 'history'", "exam_date": "the exam's date, e.g. 'Friday', '20.11'",
       "topics": "the topics, separated by commas", "?minutes_per_day": "default 60", "?time": "when to study, default 18:00"},
      risk=Risk.REVERSIBLE, group="planner")
def study_plan(ctx, subject, exam_date, topics, minutes_per_day="60", time="18:00"):
    from .. import life

    ts, _ = reminders.parse_when(str(exam_date))
    if ts is None:
        return "ERROR: I could not read the exam date"
    m = _re.fullmatch(r"(\d{1,2})(?::(\d{2}))?", str(time).strip() or "18:00")
    at = f"{int(m.group(1)):02d}:{int(m.group(2) or 0):02d}" if m else "18:00"
    minutes = int(float(str(minutes_per_day).strip() or 60))
    plan, _ids = life.study_plan(str(subject).strip(), _dt.fromtimestamp(ts).date(),
                                 _re.split(r"[,;\n]", str(topics)), minutes, at, bg=ctx.extra.get("lang") == "bg")
    return life.plan_text(plan, minutes, at, ctx.extra.get("lang") == "bg")
