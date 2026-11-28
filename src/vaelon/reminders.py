"""Reminders and notices: "remind me in 20 minutes to call mum", "напомни ми утре в 9 да платя тока".

Reminders are stored encrypted (~/.vaelon/reminders.enc). A background thread fires them: a Windows notification, and
a notice that the app shows (and reads aloud when the voice is on). Results of scheduled tasks arrive the same way.
The time is understood by code, not by the model - "in 10 minutes" is always exactly ten minutes.
"""
from __future__ import annotations

import json
import calendar as _cal
import datetime as _dt
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from . import config
from .security import vault

FILE = "reminders.enc"
_lock = threading.Lock()
NOTICES: list[dict] = []  # newest last; the app polls /notices?since=<id>
_seq = 0

UNITS = {
    "second": 1, "sec": 1, "секунд": 1, "сек": 1,
    "minute": 60, "min": 60, "минут": 60, "мин": 60,
    "hour": 3600, "hr": 3600, "час": 3600,
    "day": 86400, "ден": 86400, "дни": 86400, "дена": 86400,
    "week": 604800, "седмиц": 604800,
}
_NUM_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "five": 5, "ten": 10, "half": 0.5, "един": 1, "една": 1,
              "едно": 1, "два": 2, "две": 2, "три": 3, "пет": 5, "десет": 10, "половин": 0.5}
IN_RX = re.compile(r"(?i)\b(?:in|after|след)\s+(\d+(?:[.,]\d+)?|" + "|".join(_NUM_WORDS) + r")?\s*(?:an?\s+)?"
                   r"(second|sec|секунд|сек|minute|min|минут|мин|hour|hr|час|day|ден|дни|дена|week|седмиц)\w*")
AT_RX = re.compile(r"(?i)\b(?:at|в|във|от)\s+(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|ч\.?|часа)?(?!\d)")
DAY_RX = re.compile(r"(?i)\b(today|tomorrow|tonight|днес|утре|довечера|вдругиден)\b")
ISO_RX = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{1,2}):(\d{2}))?\b")
# full names only: "sun", "sat" or "wed" are ordinary words too ("the sun at 6", "I sat at 5")
_WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
             "понеделник": 0, "вторник": 1, "сряда": 2, "четвъртък": 3, "петък": 4, "събота": 5, "неделя": 6}
WEEKDAY_RX = re.compile(r"(?i)(?<![\w-])(?:(?:on|this|next|в|във|този|тази|следващия|следващата)\s+)?(" +
                        "|".join(sorted(_WEEKDAYS, key=len, reverse=True)) + r")(?![\w-])")
_MONTHS = {"january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4, "may": 5,
           "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
           "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
           "януари": 1, "февруари": 2, "март": 3, "април": 4, "май": 5, "юни": 6, "юли": 7, "август": 8,
           "септември": 9, "октомври": 10, "ноември": 11, "декември": 12}
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))
# "20 November", "20 ноември 2027", "November 20" and "on 20.11", "на 20.11.2026", "20/11/2026"
DAY_MONTH_RX = re.compile(r"(?i)(?<![\w.])(\d{1,2})(?:st|nd|rd|th|-?ти|-?ри|-?ви)?\s+(" + _MONTH_ALT + r")(?:\s+(\d{4}))?(?![\w])")
MONTH_DAY_RX = re.compile(r"(?i)(?<![\w])(" + _MONTH_ALT + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?(?![\w])")
NUM_DATE_RX = re.compile(r"(?i)(?:(?<![\w.])(?:on|на)\s+(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?(?![\d.])"
                         r"|(?<![\w.:])(\d{1,2})[./](\d{1,2})[./](\d{4})(?![\d])"
                         # a bare "20.11" (the tools' own examples: "20.11 at 15:00") - but not an amount or a measure
                         r"|(?<![\w.:,/])(?<!version )(?<!версия )(?<!python )(?<!at )(?<!в )(?<!във )(?<!от )(?<!около )(?<!around )(?<!by )(\d{1,2})[./](\d{1,2})(?![\d.,/])(?!\s*(?:лв|lv|eur|евро|€|\$|usd|кг|kg|г\b|g\b|л\b|l\b|ml|мл"
                         r"|%|км|km|м\b|m\b|см|cm|mm|мм|h\b|ч\b|часа|min|мин|x\b|х\b)))")
ASK_RX = re.compile(r"(?is)^\s*(?:please\s+|моля\s+)?(?:remind\s+me|set\s+(?:a\s+)?reminder|напомни\s+ми|сложи\s+(?:ми\s+)?напомняне"
                    r"|припомни\s+ми)\b[\s,:]*(.*)$")


def _next_leap(y: int) -> int:
    while not _cal.isleap(y):
        y += 1
    return y


def parse_when(text: str, now: float | None = None) -> tuple[float | None, str]:
    """(time as a timestamp or None, the text without the time words)."""
    now = now or time.time()
    rest = text
    m = ISO_RX.search(text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hh, mm = int(m.group(4) or 9), int(m.group(5) or 0)
        try:
            return time.mktime((y, mo, d, hh, mm, 0, 0, 0, -1)), (text[:m.start()] + text[m.end():]).strip()
        except (ValueError, OverflowError):
            return None, text
    m = IN_RX.search(text)
    if m:
        raw = (m.group(1) or "1").lower().replace(",", ".")
        amount = _NUM_WORDS.get(raw) if raw in _NUM_WORDS else float(raw)
        unit = next(v for k, v in UNITS.items() if m.group(2).lower().startswith(k))
        return now + amount * unit, (text[:m.start()] + text[m.end():]).strip()
    lt = time.localtime(now)
    date = None  # (year, month, day) from a date or a weekday; None = today / relative day word
    explicit_year = False
    for rx in (DAY_MONTH_RX, MONTH_DAY_RX, NUM_DATE_RX):
        m = rx.search(rest)
        if not m:
            continue
        if rx is DAY_MONTH_RX:
            d, mo, y = int(m.group(1)), _MONTHS[m.group(2).lower()], m.group(3)
        elif rx is MONTH_DAY_RX:
            mo, d, y = _MONTHS[m.group(1).lower()], int(m.group(2)), m.group(3)
        else:
            if m.group(1):
                d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
            elif m.group(4):
                d, mo, y = int(m.group(4)), int(m.group(5)), m.group(6)
            else:
                d, mo, y = int(m.group(7)), int(m.group(8)), None
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            continue
        explicit_year = bool(y)
        year = (int(y) + 2000 if len(y) == 2 else int(y)) if y else lt.tm_year
        try:  # "31.11" or "29 February" in a common year must not roll over into the next month
            _dt.date(year if explicit_year or not (mo == 2 and d == 29) else _next_leap(year), mo, d)
        except ValueError:
            return None, text
        if mo == 2 and d == 29 and not explicit_year:
            year = _next_leap(year)
        date = (year, mo, d)
        rest = rest[:m.start()] + rest[m.end():]
        break
    if date is None:
        m = WEEKDAY_RX.search(rest)
        if m:
            ahead = (_WEEKDAYS[m.group(1).lower()] - lt.tm_wday) % 7
            ahead = ahead or 7  # "on Friday" said on a Friday: next week (today would be "today")
            when_day = time.localtime(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + ahead, 12, 0, 0, 0, 0, -1)))
            date = (when_day.tm_year, when_day.tm_mon, when_day.tm_mday)
            rest = rest[:m.start()] + rest[m.end():]
    day = DAY_RX.search(rest)
    at = AT_RX.search(rest)
    if not day and not at and date is None:
        return None, text
    add_days = 0
    hh, mm = 9, 0
    if day:
        word = day.group(1).lower()
        add_days = {"tomorrow": 1, "утре": 1, "вдругиден": 2}.get(word, 0)
        if word in ("tonight", "довечера"):
            hh = 20
        rest = (rest[:day.start()] + rest[day.end():])
    if at:
        hh, mm = int(at.group(1)), int(at.group(2) or 0)
        suffix = (at.group(3) or "").lower()
        if suffix == "pm" and hh < 12:
            hh += 12
        if suffix == "am" and hh == 12:
            hh = 0
        if hh > 23 or mm > 59:
            return None, text
        at2 = AT_RX.search(rest)
        if at2:
            rest = rest[:at2.start()] + rest[at2.end():]
    if date is not None:
        try:
            ts = time.mktime((date[0], date[1], date[2], hh, mm, 0, 0, 0, -1))
        except (OverflowError, ValueError):
            return None, text
        if not explicit_year and ts < now - 86400:
            ts = time.mktime((date[0] + 1, date[1], date[2], hh, mm, 0, 0, 0, -1))  # "20 March" said in November: next year
        return ts, re.sub(r"\s+", " ", rest).strip()
    ts = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + add_days, hh, mm, 0, 0, 0, -1))
    if ts <= now and not day:
        ts += 86400  # "at 8" when it is already past 8: tomorrow
    return ts, re.sub(r"\s+", " ", rest).strip()


def clean_text(rest: str) -> str:
    """'to call mum' / 'да платя тока' / 'that the oven is on' -> the thing to remember."""
    rest = re.sub(r"(?i)^[\s,:-]*(?:to|that|about|да|че|за)\s+", "", rest.strip())
    return rest.strip(" .,:;-") or "Reminder"


def _path() -> Path:
    return config.HOME / FILE


def load(strict: bool = False) -> list[dict]:
    """The reminders. `strict` (before every write): a file that exists but cannot be read raises - an empty-looking
    read followed by a write would wipe every reminder."""
    p = _path()
    if not p.exists():
        return []
    try:
        return json.loads(vault.decrypt_text(p.read_text("utf-8").strip()))
    except Exception:
        if strict:
            raise RuntimeError("the reminders file could not be read, so nothing was changed")
        return []


def _store(items: list[dict]) -> None:
    config.HOME.mkdir(parents=True, exist_ok=True)
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(vault.encrypt_text(json.dumps(items, ensure_ascii=False)), "utf-8")
    vault.replace(tmp, _path())


def add(when: float, text: str) -> dict:
    item = {"id": uuid.uuid4().hex[:6], "when": float(when), "text": text.strip()[:300]}
    with _lock:
        _store(load(strict=True) + [item])
    return item


def cancel(rid: str) -> bool:
    with _lock:
        items = load(strict=True)
        kept = [i for i in items if i["id"] != rid]
        if len(kept) != len(items):
            _store(kept)
        return len(kept) != len(items)


def describe(ts: float, bg: bool = False, now: float | None = None) -> str:
    now = now or time.time()
    lt, today = time.localtime(ts), time.localtime(now)
    hhmm = time.strftime("%H:%M", lt)
    days = (time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
            - time.mktime((today.tm_year, today.tm_mon, today.tm_mday, 0, 0, 0, 0, 0, -1))) / 86400
    if round(days) == 0:
        return ("днес в " if bg else "today at ") + hhmm
    if round(days) == 1:
        return ("утре в " if bg else "tomorrow at ") + hhmm
    return time.strftime("%d.%m.%Y ", lt) + ("в " if bg else "at ") + hhmm


def notify(title: str, text: str, kind: str = "reminder", toast: bool = True) -> dict:
    """Tell the user something now: a notice for the app, and a Windows notification."""
    global _seq
    with _lock:
        _seq += 1
        note = {"id": _seq, "ts": time.time(), "kind": kind, "title": title[:80], "text": text[:600]}
        NOTICES.append(note)
        del NOTICES[:-50]
    if toast:
        threading.Thread(target=windows_toast, args=(title, text), daemon=True).start()
    return note


def notices_since(last: int) -> list[dict]:
    with _lock:
        return [n for n in NOTICES if n["id"] > last]


TOAST_PS1 = r"""param($TitleFile, $TextFile)
$title = [IO.File]::ReadAllText($TitleFile, [Text.Encoding]::UTF8)
$text = [IO.File]::ReadAllText($TextFile, [Text.Encoding]::UTF8)
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$nodes = $xml.GetElementsByTagName("text")
$nodes.Item(0).AppendChild($xml.CreateTextNode($title)) | Out-Null
$nodes.Item(1).AppendChild($xml.CreateTextNode($text)) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show($toast)
"""


def windows_toast(title: str, text: str) -> bool:
    """A native notification. Windows: the words travel in files, never on a command line. macOS: Notification
    Center, the words as arguments. Best effort."""
    if sys.platform == "darwin":
        from . import platform_mac

        return platform_mac.notify(title, text)
    if sys.platform != "win32":
        return False
    try:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "toast.ps1").write_text(TOAST_PS1, "utf-8-sig")
            (d / "title.txt").write_text(title[:80], "utf-8")
            (d / "text.txt").write_text(text[:300], "utf-8")
            r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(d / "toast.ps1"),
                                str(d / "title.txt"), str(d / "text.txt")], capture_output=True, timeout=20,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return r.returncode == 0
    except Exception:
        return False


def fire_due(now: float | None = None, toast: bool = True) -> list[dict]:
    """Fire every reminder whose time has come (each exactly once). Returns the fired ones."""
    now = now or time.time()
    with _lock:
        items = load()
        due = [i for i in items if i["when"] <= now]
        if due:
            _store([i for i in items if i["when"] > now])
    for i in due:
        notify("Vaelon - reminder", i["text"], "reminder", toast)
    return due


_watching = False


def watch(poll_seconds: float = 5.0, cfg=None) -> None:
    """Start the background thread that fires reminders (once per process). `cfg` (the app's settings) tells where
    recurring invoices put their PDFs."""
    global _watching
    if _watching:
        return
    _watching = True

    def loop():
        from . import company

        company.system()  # this thread is Vaelon itself: it only marks what it announced
        try:
            conf = cfg or config.Config.load()
        except Exception:
            conf = None
        while True:
            try:
                fire_due()
            except Exception:
                pass
            try:  # appointments in the calendar: announced `remind` minutes before they start
                from . import agenda

                agenda.fire_due()
            except Exception:
                pass
            for d in company.all_dirs():  # every company's bills and deals, not only the one that is open
                try:  # bound to that company and its owner: its PDFs go to its own output folder
                    company.bind(company.owner_id() if company.enabled() else None,
                                 company.PERSONAL if d == config.HOME else d.name)
                except Exception:
                    continue
                with company.use_dir(d):
                    try:  # bills: a few days before the due date, on the day, and once when overdue
                        from . import bills

                        bills.fire_due()
                    except Exception:
                        pass
                    try:  # deals: the day of a next step, and a passed close date
                        from . import deals

                        deals.fire_due()
                    except Exception:
                        pass
                    try:  # quotes: a few days before they expire, and once when they have
                        from . import quotes

                        quotes.fire_due()
                    except Exception:
                        pass
                    try:  # recurring invoices: made on their day (never sent)
                        from . import recurring

                        recurring.run_due(conf)
                    except Exception:
                        pass
                    try:  # overdue invoices: a reminder DRAFT for the client (never sent by itself)
                        from . import payreminders

                        payreminders.fire_due()
                    except Exception:
                        pass
                company.unbind()
            company.unbind()
            time.sleep(poll_seconds)

    threading.Thread(target=loop, daemon=True, name="vaelon-reminders").start()


def from_request(request: str, bg: bool, now: float | None = None) -> str | None:
    """Answer for 'remind me ...' requests, or None if this is not one / the time is unclear."""
    m = ASK_RX.match(request or "")
    if not m:
        return None
    when, rest = parse_when(m.group(1), now)
    if when is None:
        return None  # no clear time: let the model ask or use the tool
    item = add(when, clean_text(rest))
    return (f"Ще ти напомня {describe(when, True, now)}: {item['text']}" if bg
            else f"I will remind you {describe(when, False, now)}: {item['text']}")
