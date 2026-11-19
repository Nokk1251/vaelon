"""The calendar: appointments, meetings, birthdays - with a time, a length, a place, a reminder and repeats.

    "запиши среща със зъболекаря в петък в 10"   "what do I have tomorrow?"   "move the dentist to 11"

Stored ENCRYPTED in ~/.vaelon/calendar.enc (vault, AES-256-GCM): what you do and where is personal.
Times are local wall-clock times ("2026-11-20T10:00") - a meeting at 10 stays at 10 when the clocks change.
Repeats: daily, weekly, monthly (same day; a 31st falls back to the month's last day), yearly.
Reminders: the reminder thread (reminders.watch) calls `fire_due` - each occurrence is announced once,
`remind` minutes before it starts (a Windows notification + a line in the app, read aloud when the voice is on).
.ics files go both ways, so Google Calendar, Outlook and phones can share the same appointments.
"""
from __future__ import annotations

import calendar as _cal
import json
import re
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import config
from .security import vault

FILE = "calendar.enc"
REPEATS = ("", "daily", "weekly", "monthly", "yearly")
_lock = threading.Lock()
_BG_DAYS = ["понеделник", "вторник", "сряда", "четвъртък", "петък", "събота", "неделя"]
_BG_MONTHS = ["януари", "февруари", "март", "април", "май", "юни", "юли", "август", "септември", "октомври",
              "ноември", "декември"]


# ---------------------------------------------------------------- storage

def _path() -> Path:
    return config.HOME / FILE


def load(strict: bool = False) -> list[dict]:
    """`strict` (before every write): an unreadable file raises instead of being replaced by an empty one."""
    p = _path()
    if not p.exists():
        return []
    try:
        items = json.loads(vault.decrypt_text(p.read_text("utf-8").strip()))
        return items if isinstance(items, list) else []
    except Exception:
        if strict:
            raise RuntimeError(f"{FILE} could not be read, so nothing was changed (the file is left as it is)")
        return []


def _store(items: list[dict]) -> None:
    config.HOME.mkdir(parents=True, exist_ok=True)
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(vault.encrypt_text(json.dumps(items, ensure_ascii=False)), "utf-8")
    vault.replace(tmp, _path())


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M")


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


# ---------------------------------------------------------------- events

def add(title: str, start: datetime, minutes: int = 60, all_day: bool = False, place: str = "", notes: str = "",
        repeat: str = "", remind: int | None = 15) -> dict:
    title = re.sub(r"\s+", " ", str(title)).strip()[:200]
    if not title:
        raise ValueError("the event needs a title")
    if repeat not in REPEATS:
        raise ValueError("repeat must be daily, weekly, monthly or yearly")
    if all_day:
        start = start.replace(hour=0, minute=0)
        minutes = 24 * 60
    ev = {"id": uuid.uuid4().hex[:6], "title": title, "start": iso(start), "minutes": max(1, int(minutes)),
          "all_day": bool(all_day), "place": str(place).strip()[:200], "notes": str(notes).strip()[:1000],
          "repeat": repeat, "remind": None if remind is None else max(0, int(remind)), "alerted": "",
          "skip": []}
    with _lock:
        _store(load(strict=True) + [ev])
    return ev


def get(eid: str) -> dict | None:
    return next((e for e in load() if e["id"] == eid), None)


def update(eid: str, **changes) -> dict | None:
    with _lock:
        items = load(strict=True)
        for e in items:
            if e["id"] == eid:
                e.update(changes)
                _store(items)
                return e
    return None


def remove(eid: str) -> dict | None:
    with _lock:
        items = load(strict=True)
        gone = next((e for e in items if e["id"] == eid), None)
        if gone:
            _store([e for e in items if e["id"] != eid])
        return gone


def restore(ev: dict) -> None:
    """Put an event back exactly as it was (undo)."""
    with _lock:
        items = [e for e in load(strict=True) if e["id"] != ev["id"]]
        _store(items + [ev])


# ---------------------------------------------------------------- occurrences

def _step(start: datetime, repeat: str, n: int) -> datetime:
    if repeat == "daily":
        return start + timedelta(days=n)
    if repeat == "weekly":
        return start + timedelta(weeks=n)
    if repeat in ("monthly", "yearly"):
        months = n if repeat == "monthly" else 12 * n
        y, m = divmod(start.month - 1 + months, 12)
        y, m = start.year + y, m + 1
        return start.replace(year=y, month=m, day=min(start.day, _cal.monthrange(y, m)[1]))
    return start


def occurrences(ev: dict, frm: datetime, to: datetime) -> list[datetime]:
    """Start times of this event that overlap [frm, to)."""
    start, length = parse_iso(ev["start"]), timedelta(minutes=ev.get("minutes", 60))
    skip = set(ev.get("skip") or [])
    if not ev.get("repeat"):
        return [start] if start < to and start + length > frm and iso(start) not in skip else []
    out, n = [], 0
    if ev["repeat"] in ("daily", "weekly") and frm > start:  # jump close to the window instead of walking years
        days = 1 if ev["repeat"] == "daily" else 7
        n = max(0, int((frm - start - length).total_seconds() // (days * 86400)))
    for _ in range(2000):
        s = _step(start, ev["repeat"], n)
        if s >= to:
            break
        if s + length > frm and iso(s) not in skip:
            out.append(s)
        n += 1
    return out


def between(frm: datetime, to: datetime) -> list[tuple[datetime, dict]]:
    """Every occurrence in [frm, to), in time order."""
    rows = [(s, e) for e in load() for s in occurrences(e, frm, to)]
    return sorted(rows, key=lambda r: (r[0], r[1]["title"]))


def clashes(start: datetime, minutes: int, ignore: str = "") -> list[tuple[datetime, dict]]:
    """Timed events that overlap a new slot (all-day events do not block a slot)."""
    end = start + timedelta(minutes=minutes)
    return [(s, e) for s, e in between(start, end) if e["id"] != ignore and not e.get("all_day")]


def find(query: str, days_back: int = 30, days_ahead: int = 400) -> list[tuple[datetime, dict]]:
    q = query.lower().strip()
    now = datetime.now()
    hits = []
    for e in load():
        if q and not any(q in str(e.get(k, "")).lower() for k in ("title", "place", "notes")):
            continue
        occ = occurrences(e, now - timedelta(days=days_back), now + timedelta(days=days_ahead))
        upcoming = [s for s in occ if s + timedelta(minutes=e.get("minutes", 60)) >= now]
        hits.append(((upcoming or occ or [parse_iso(e["start"])])[0], e))
    return sorted(hits, key=lambda r: r[0])


# ---------------------------------------------------------------- words

def day_label(d: date, bg: bool, today: date | None = None) -> str:
    today = today or date.today()
    diff = (d - today).days
    if diff == 0:
        return "Днес" if bg else "Today"
    if diff == 1:
        return "Утре" if bg else "Tomorrow"
    if bg:
        return f"{_BG_DAYS[d.weekday()].capitalize()}, {d.day} {_BG_MONTHS[d.month - 1]}"
    return d.strftime("%A, %d %B").replace(" 0", " ")


def line(start: datetime, ev: dict, bg: bool, ids: bool = True) -> str:
    if ev.get("all_day"):
        when = "цял ден" if bg else "all day"
    else:
        end = start + timedelta(minutes=ev.get("minutes", 60))
        when = f"{start:%H:%M}-{end:%H:%M}"
    extra = f" ({ev['place']})" if ev.get("place") else ""
    rep = {"daily": " ↻ всеки ден" if bg else " ↻ daily", "weekly": " ↻ всяка седмица" if bg else " ↻ weekly",
           "monthly": " ↻ всеки месец" if bg else " ↻ monthly", "yearly": " ↻ всяка година" if bg else " ↻ yearly"}.get(ev.get("repeat"), "")
    return f"{when}  {ev['title']}{extra}{rep}" + (f"  [id {ev['id']}]" if ids else "")


def agenda_text(frm: datetime, to: datetime, bg: bool, ids: bool = True) -> str:
    """The days and their events. `ids`: for the model (it needs them to move or cancel); not for people."""
    rows = between(frm, to)
    if not rows:
        return ("Нямаш нищо в календара за този период." if bg else "Nothing in your calendar for that period.")
    out, last = [], None
    for s, e in rows:
        d = max(s, frm).date() if e.get("all_day") else s.date()
        if d != last:
            out.append(f"{day_label(d, bg)}:")
            last = d
        out.append("• " + line(s, e, bg, ids))
    return "\n".join(out)


def span(text: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    """'today' / 'tomorrow' / 'this week' / 'next week' / 'this month' / a date -> [from, to). Default: 7 days."""
    now = now or datetime.now()
    low = (text or "").lower()
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if re.search(r"tomorrow|утре", low):
        return day0 + timedelta(days=1), day0 + timedelta(days=2)
    if re.search(r"next week|следващата седмица", low):
        monday = day0 - timedelta(days=day0.weekday()) + timedelta(days=7)
        return monday, monday + timedelta(days=7)
    if re.search(r"week|седмица", low):
        return day0, day0 + timedelta(days=7 - day0.weekday())
    if re.search(r"month|месец", low):
        return day0, day0 + timedelta(days=31)
    if re.search(r"today|днес|tonight|довечера", low):
        return day0, day0 + timedelta(days=1)
    if low.strip():
        from . import reminders

        ts, _ = reminders.parse_when(text, now.timestamp())
        if ts:
            d = datetime.fromtimestamp(ts).replace(hour=0, minute=0)
            return d, d + timedelta(days=1)
    return day0, day0 + timedelta(days=7)


def minutes_of(text: str) -> tuple[int, bool]:
    """'90 min' / '1.5h' / '2 часа' / 'all day' -> (minutes, all day). Default 60."""
    low = str(text or "").lower().strip()
    if not low:
        return 60, False
    if re.search(r"all[- ]?day|whole day|цял(ия)? ден", low):
        return 24 * 60, True
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(h|hour|hours|час|часа|ч)\b", low)
    if m:
        return max(5, round(float(m.group(1).replace(",", ".")) * 60)), False
    m = re.search(r"(\d+)\s*(m|min|minute|minutes|мин|минути|минута)?\b", low)
    if m:
        return max(5, int(m.group(1))), False
    return 60, False


# ---------------------------------------------------------------- reminders

def fire_due(now: datetime | None = None, toast: bool = True) -> list[str]:
    """Announce every occurrence whose reminder time has come (once each). Called by the reminder thread."""
    from . import reminders

    now = now or datetime.now()
    fired = []
    with _lock:
        items, changed = load(strict=True), False
        for e in items:
            if e.get("remind") is None:
                continue
            lead = timedelta(minutes=e["remind"])
            for s in occurrences(e, now - timedelta(minutes=1), now + lead + timedelta(minutes=1)):
                if s - lead <= now <= s + timedelta(minutes=1) and (not e.get("alerted") or iso(s) > e["alerted"]):
                    e["alerted"], changed = iso(s), True
                    if e.get("all_day"):  # a birthday, an exam day: "tomorrow", never "at 00:00"
                        when = "today" if s.date() <= now.date() else "tomorrow" if (s.date() - now.date()).days == 1 else f"on {s:%d.%m}"
                    else:
                        when = "now" if e["remind"] == 0 else f"at {s:%H:%M}"
                    fired.append(f"{e['title']} {when}" + (f" - {e['place']}" if e.get("place") else ""))
        if changed:
            _store(items)
    for text in fired:
        reminders.notify("Vaelon - calendar", text, "reminder", toast)
    return fired


# ---------------------------------------------------------------- .ics (iCalendar)

def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line_: str) -> str:
    raw, out = line_.encode("utf-8"), []
    while len(raw) > 74:
        cut = 74
        while cut and (raw[cut] & 0xC0) == 0x80:  # never split a multi-byte character
            cut -= 1
        out.append(raw[:cut].decode("utf-8"))
        raw = b" " + raw[cut:]
    out.append(raw.decode("utf-8"))
    return "\r\n".join(out)


def to_ics(events: list[dict]) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Vaelon//Calendar//EN", "CALSCALE:GREGORIAN"]
    for e in events:
        s = parse_iso(e["start"])
        lines += ["BEGIN:VEVENT", f"UID:{e['id']}@vaelon.local", f"DTSTAMP:{stamp}"]
        if e.get("all_day"):
            lines += [f"DTSTART;VALUE=DATE:{s:%Y%m%d}", f"DTEND;VALUE=DATE:{s + timedelta(days=1):%Y%m%d}"]
        else:
            lines += [f"DTSTART:{s:%Y%m%dT%H%M%S}", f"DTEND:{s + timedelta(minutes=e.get('minutes', 60)):%Y%m%dT%H%M%S}"]
        lines.append(f"SUMMARY:{_esc(e['title'])}")
        if e.get("place"):
            lines.append(f"LOCATION:{_esc(e['place'])}")
        if e.get("notes"):
            lines.append(f"DESCRIPTION:{_esc(e['notes'])}")
        if e.get("repeat"):
            lines.append(f"RRULE:FREQ={e['repeat'].upper()}")
        for x in e.get("skip") or []:
            lines.append(f"EXDATE;VALUE=DATE:{parse_iso(x):%Y%m%d}" if e.get("all_day") else f"EXDATE:{parse_iso(x):%Y%m%dT%H%M%S}")
        if e.get("remind") is not None:
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_esc(e['title'])}",
                      f"TRIGGER:-PT{int(e['remind'])}M", "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"


def _unesc(s: str) -> str:
    return re.sub(r"\\(.)", lambda m: "\n" if m.group(1) in "nN" else m.group(1), s)


def _ics_time(value: str, params: str) -> tuple[datetime, bool] | None:
    value = value.strip()
    try:
        if "VALUE=DATE" in params.upper() or re.fullmatch(r"\d{8}", value):
            return datetime.strptime(value[:8], "%Y%m%d"), True
        if value.endswith("Z"):  # UTC: shown in local time
            return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=__import__("datetime").timezone.utc).astimezone().replace(tzinfo=None), False
        local = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
        tz = re.search(r"(?i)TZID=([^;:]+)", params or "")
        if tz:  # "10:00 in New York" is 17:00 here: converted to this computer's time
            try:
                from zoneinfo import ZoneInfo

                return local.replace(tzinfo=ZoneInfo(tz.group(1).strip('"'))).astimezone().replace(tzinfo=None), False
            except Exception:
                pass  # an unknown zone name (Windows names like "FLE Standard Time"): kept as written
        return local, False
    except ValueError:
        return None


def from_ics(text: str) -> list[dict]:
    """VEVENTs of an .ics file as event fields (not stored). Unknown or broken entries are skipped."""
    raw = re.sub(r"\r?\n[ \t]", "", text.replace("\r\n", "\n"))  # unfold
    out = []
    for block in re.findall(r"BEGIN:VEVENT\n(.*?)\nEND:VEVENT", raw, re.S):
        fields = {}
        for ln in block.split("\n"):
            if ":" not in ln or ln.startswith(("BEGIN:", "END:")):
                continue
            key, val = ln.split(":", 1)
            name, _, params = key.partition(";")
            fields.setdefault(name.upper(), (params, val))
        if "DTSTART" not in fields:
            continue
        st = _ics_time(fields["DTSTART"][1], fields["DTSTART"][0])
        if not st:
            continue
        start, all_day = st
        minutes = 24 * 60 if all_day else 60
        if "DTEND" in fields:
            en = _ics_time(fields["DTEND"][1], fields["DTEND"][0])
            if en and en[0] > start:
                minutes = int((en[0] - start).total_seconds() // 60)
        rule = fields.get("RRULE", ("", ""))[1]
        rr = re.search(r"FREQ=(DAILY|WEEKLY|MONTHLY|YEARLY)", rule, re.I)
        # Vaelon repeats every day / week / month / year for ever: a rule it cannot follow exactly (every 2 weeks,
        # until a date, 10 times, Mon+Wed+Fri) is imported as ONE event and marked, never as a wrong endless series
        complex_rule = bool(rr) and bool(re.search(r"(?i)INTERVAL=(?!1\b)\d|UNTIL=|COUNT=|BYDAY=[^;]*,|BYSETPOS|BYMONTHDAY=[^;]*,", rule))
        skip = []
        for m_ in re.finditer(r"(?m)^EXDATE[^:]*:(.+)$", block):
            for v in m_.group(1).split(","):
                ex = _ics_time(v, "")
                if ex:
                    skip.append(ex[0].date().isoformat())
        out.append({"uid": fields.get("UID", ("", ""))[1].strip()[:200], "skip": skip, "simplified": complex_rule,
                    "title": _unesc(fields.get("SUMMARY", ("", "(no title)"))[1])[:200] or "(no title)", "start": start,
                    "minutes": minutes, "all_day": all_day, "place": _unesc(fields.get("LOCATION", ("", ""))[1])[:200],
                    "notes": _unesc(fields.get("DESCRIPTION", ("", ""))[1])[:1000],
                    "repeat": rr.group(1).lower() if rr and not complex_rule else ""})
    return out
