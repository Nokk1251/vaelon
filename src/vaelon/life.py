"""Life events Vaelon handles a step further than a plain calendar entry.

    "имам изпит по математика след 3-4 дни"  -> the exam goes in the calendar (reminder the day before), and Vaelon
                                                offers a study plan: "теми: дроби, уравнения; 1 час на ден" builds it
    "рожденият ден на мама е на 12 март"     -> a yearly event, reminded the day before at 09:00 (time for a gift)
    "our anniversary is June 20", "имен ден на Иван е на 7 януари" -> the same, yearly
    "забравих рождения ден на Петър, беше вчера" -> recorded for next year + an offer to write an apology

The study plan (`study_plan`) is made by code, so it is the same every time and needs no model: the topics are
spread over the days left, the last day is a mock exam and a review, each session is a calendar event with a
reminder. What to read and the practice questions are the model's job (skill exam-prep).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

# a reminder for an all-day event, in minutes before its 00:00: 900 = 09:00 the day before
DAY_BEFORE_9 = 900

EXAM_WORDS = r"test|exam|quiz|midterm|final exam|finals|тест|изпит|контролно|класно|матура|зачот|колоквиум|изпитване"
EXAM_RX = re.compile(r"(?is)^\s*(?:i\s+have|i've\s+got|i\s+got|there\s+is|there's|имам|ще\s+имам|предстои\s+ми|чака\s+ме)\s+"
                     r"(?:a|an|my|the|един|една|едно)?\s*([a-z][a-z\s]{0,30}?\s+)?(" + EXAM_WORDS + r")\b(?!\s*(?:drive|run|ride|flight|match|game|print|tube|case|kit|lab)\b)(.*)$")  # "a history exam"
# "теми: ...", "topics: ...", "the topics are ...", "темите са ..." - a colon or a plural "are/са" is required
# ("The topic is too hard for me" is not a list of topics - found by the code review 2026-11-15)
STUDY_RX = re.compile(r"(?is)^\s*(?:the\s+)?(?:topics?|subjects?|теми(?:те)?|материал(?:ът)?|влизат)\s*:\s*(.+)$|"
                      r"^\s*(?:the\s+)?topics\s+are\s+(.+)$|^\s*темите\s+(?:за\s+изпита\s+)?са\s*:?\s*(.+)$")
STUDY_AT_RX = re.compile(r"(?i)(?:\b(?:at|в|във)\s+(\d{1,2})(?::(\d{2}))?(?!\d)\s*(?:ч\.?|часа|h)?|"
                         r"\bот\s+(\d{1,2})(?::(\d{2}))?\s*(?:ч\.?|часа)(?![\w]))")  # "от 10 до 20" alone is no time
PER_DAY_RX = re.compile(r"(?i)(\d+(?:[.,]\d+)?)\s*(h|hours?|час(?:а)?|ч\.?|min|minutes?|мин(?:ути)?)\s*(?:a|per|на)?\s*(?:day|ден)")
BDAY_RX = re.compile(r"(?is)^\s*(?:(?:the\s+)?birthday\s+of\s+(.+?)|(.+?)'s\s+birthday|рожден(?:ият)?\s+ден\s+на\s+(.+?)|"
                     r"(.+?)\s+има\s+рожден\s+ден)\s+(?:is\s+|е\s+)?(?:on\s+|на\s+)?(.+)$")
NAMEDAY_RX = re.compile(r"(?is)^\s*(?:(.+?)'s\s+name\s+day|имен(?:ият)?\s+ден\s+на\s+(.+?)|(.+?)\s+има\s+имен\s+ден)\s+"
                        r"(?:is\s+|е\s+)?(?:on\s+|на\s+)?(.+)$")
ANNIV_RX = re.compile(r"(?is)^\s*(?:our\s+(?:wedding\s+)?anniversary|годишнината\s+ни|сватбената\s+ни\s+годишнина|"
                      r"(?:the\s+)?anniversary\s+of\s+(.+?)|годишнина(?:та)?\s+(?:на|от)\s+(.+?))\s+(?:is\s+|е\s+)?(?:on\s+|на\s+)?(.+)$")
FORGOT_RX = re.compile(r"(?is)^\s*(?:i\s+forgot\s+(?:about\s+)?(.+?)'s\s+birthday|i\s+forgot\s+the\s+birthday\s+of\s+(.+?)|"
                       r"забравих\s+(?:за\s+)?рождени(?:я|ят)\s+ден\s+на\s+(.+?))(?:[\s,.;-]+(.*))?$")
_RANGE_RX = re.compile(r"(\d+)\s*(?:-|–|до|or|или)\s*\d+(\s*(?:days?|дни|дена|weeks?|седмици))")


def _owner(name: str, bg: bool) -> str:
    return re.sub(r"\s+", " ", name).strip(" ,.:;-\"'„“")[:60]


def _next_yearly(text: str, today: date) -> date | None:
    """The next time a yearly date comes (today counts). 29 February: the 28th in years without it."""
    from . import bills as B

    if FEB29_RX.search(text):
        day, month = 29, 2
    else:
        d, _ = B.find_date(text, today)
        if not d:
            return None
        day, month = d.day, d.month
    for y in (today.year, today.year + 1):
        x = _safe_date(y, month, day)
        if x >= today:
            return x
    return _safe_date(today.year + 1, month, day)


FEB29_RX = re.compile(r"(?i)(?<!\d)29\s*(?:[./-]\s*0?2(?!\d)|-?(?:ти)?\s+(?:февруари|february|feb)\b)")


def _safe_date(y: int, month: int, day: int) -> date:
    try:
        return date(y, month, day)
    except ValueError:  # 29 February in a year without it
        return date(y, month, 28)


def _add_yearly(title: str, d: date, notes: str = "") -> dict:
    from . import agenda
    from .security import undo

    ev = agenda.add(title, datetime.combine(d, datetime.min.time()), all_day=True, repeat="yearly", notes=notes,
                    remind=DAY_BEFORE_9)
    undo.push(f"add {title}", lambda: agenda.remove(ev["id"]))
    return ev


def _day(d: date, bg: bool) -> str:
    from . import agenda

    return agenda.day_label(d, bg).lower() if (d - date.today()).days <= 1 else agenda.day_label(d, bg)


# ---------------------------------------------------------------- exams

def exam(request: str, bg: bool, now: datetime | None = None) -> str | None:
    from . import reminders
    from .tools import planner

    m = EXAM_RX.match(request)
    if not m:
        return None
    pre, kind, rest = (m.group(1) or "").strip(), m.group(2).lower(), m.group(3)
    ranged = _RANGE_RX.search(rest)
    rest = _RANGE_RX.sub(lambda r: r.group(1) + r.group(2), rest)  # "3-4 days": plan for the earlier one, to be safe
    now = now or datetime.now()
    ts, left = reminders.parse_when(rest, now.timestamp())
    if ts is None:
        return None  # no date: the model asks
    when = datetime.fromtimestamp(ts)
    timed = bool(reminders.AT_RX.search(rest))
    subject = re.sub(r"(?i)^(?:по|on|in|for|of|at)\s+", "", left.strip(" ,.:;-"))
    subject = re.sub(r"(?i)\s+(?:on|at|в|на|след|in)$", "", subject).strip(" ,.:;-")[:80] or pre[:80]
    word = {"тест": "Тест", "изпит": "Изпит", "контролно": "Контролно", "класно": "Класна работа", "матура": "Матура"}.get(kind, kind.capitalize())
    title = (f"{word} по {subject}" if bg else f"{word}: {subject}") if subject else word
    try:
        ev, _ = planner.schedule(title, when.strftime("%Y-%m-%d %H:%M") if timed else when.strftime("%Y-%m-%d"), "120 min" if timed else "",
                                 notes="exam", remind=str(DAY_BEFORE_9) if not timed else "1 day")
    except ValueError:
        return None
    days = (when.date() - now.date()).days
    note = (" (взех по-ранния ден, за по-сигурно)" if bg else " (I took the earlier day, to be safe)") if ranged else ""
    if bg:
        return (f"Записах: {title} - {_day(when.date(), True)}{' в ' + when.strftime('%H:%M') if timed else ''}, след {days} "
                f"{'ден' if days == 1 else 'дни'}{note}. Ще ти напомня предния ден.\n"
                f"Да ти направя план за учене? Кажи кои теми влизат и колко време на ден имаш - например "
                f"„теми: дроби, уравнения, проценти; 1 час на ден“. Ще разпределя темите по дните, последния ден - "
                f"пробен изпит, и ще сложа всяко учене в календара.")
    return (f"Saved: {title} - {_day(when.date(), False)}{' at ' + when.strftime('%H:%M') if timed else ''}, in {days} "
            f"day{'' if days == 1 else 's'}{note}. I will remind you the day before.\n"
            f"Want a study plan? Tell me the topics and how much time you have a day - e.g. \"topics: fractions, "
            f"equations, percentages; 1 hour a day\". I will spread them over the days, make the last day a mock exam, "
            f"and put every session in your calendar.")


def next_exam(now: datetime | None = None) -> dict | None:
    """The exam saved LAST that is still ahead (within 60 days): "теми: ..." answers the exam just mentioned,
    not the nearest one."""
    from . import agenda

    now = now or datetime.now()
    order = {e["id"]: n for n, e in enumerate(agenda.load())}  # stored in the order they were added
    ahead = [(s, e) for s, e in agenda.between(now.replace(hour=0, minute=0), now + timedelta(days=60)) if e.get("notes") == "exam"]
    if not ahead:
        return None
    s, e = max(ahead, key=lambda r: order.get(r[1]["id"], -1))
    return {**e, "when": s}


def study_plan(subject: str, exam_day: date, topics: list[str], minutes: int = 60, at: str = "18:00",
               today: date | None = None, bg: bool = False) -> tuple[list[tuple[date, str]], list[str]]:
    """Spread the topics over the days before the exam. Returns ([(day, what)], [event ids added])."""
    from . import agenda
    from .security import undo

    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(at).strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError("the study time must look like 18:00")
    hh, mm = int(m.group(1)), int(m.group(2))
    minutes = max(15, min(480, int(minutes)))  # between a quarter of an hour and 8 hours a day
    real_today = date.today()
    today = today or real_today
    # today counts only while its study time is still ahead (an 08:00 session must not land in the past)
    later_today = today != real_today or datetime.now().time() < datetime.min.time().replace(hour=hh, minute=mm)
    start = today if later_today else today + timedelta(days=1)
    days = [start + timedelta(days=k) for k in range((exam_day - start).days)]
    topics = [t for t in (re.sub(r"\s+", " ", x).strip(" .") for x in topics) if t][:30]
    if not days:
        raise ValueError("there is no day left before the exam")
    if not topics:
        raise ValueError("tell me the topics")
    plan: list[tuple[date, str]] = []
    if len(days) == 1:
        plan = [(days[0], ", ".join(topics) + " + a mock test")]
    else:
        learn = days[:-1]
        per = [[] for _ in learn]
        for n, t in enumerate(topics):
            per[n * len(learn) // len(topics) if len(topics) >= len(learn) else n % len(learn)].append(t)
        for n, d in enumerate(learn):
            plan.append((d, ", ".join(per[n]) if per[n] else "review: " + ", ".join(topics[: max(1, n % len(topics) + 1)][-2:])))
        plan.append((days[-1], "mock exam + review of the weak spots"))
    ids = []
    for d, what in plan:
        label = ("Учене" if bg else "Study") + (f" ({subject})" if subject else "")
        shown = (what.replace("mock exam + review of the weak spots", "пробен изпит + преговор")
                 .replace(" + a mock test", " + пробен тест").replace("review: ", "преговор: ")) if bg else what
        ev = agenda.add(f"{label}: {shown}", datetime.combine(d, datetime.min.time()).replace(hour=hh, minute=mm),
                        max(15, minutes), notes="study plan", remind=10)
        ids.append(ev["id"])
    undo.push(f"study plan {subject}", lambda: [agenda.remove(i) for i in ids])
    return plan, ids


def plan_text(plan: list[tuple[date, str]], minutes: int, at: str, bg: bool) -> str:
    head = (f"Планът (по {minutes} мин на ден от {at}, всяко учене е в календара с напомняне 10 мин преди):" if bg
            else f"The plan ({minutes} min a day at {at}, each session is in your calendar with a reminder 10 min before):")
    rows = []
    for d, what in plan:
        if bg:
            what = what.replace("mock exam + review of the weak spots", "пробен изпит + преговор на слабите места") \
                .replace(" + a mock test", " + пробен тест").replace("review: ", "преговор: ")
        rows.append(f"• {_day(d, bg)}: {what}")
    tail = ("Искаш ли за всяка тема кратко обяснение и задачи за упражнение (и пробен изпит с отговори)?" if bg
            else "Want a short explanation and practice questions for each topic (and a mock exam with answers)?")
    return "\n".join([head, *rows, tail])


def study(request: str, bg: bool) -> str | None:
    """'теми: дроби, уравнения; 1 час на ден' right after an exam was saved -> the plan in the calendar."""
    m = STUDY_RX.match(request)
    if not m:
        return None
    ex = next_exam()
    if not ex:
        return None
    body = next(g for g in m.groups() if g)
    minutes = 60
    pm = PER_DAY_RX.search(body)
    if pm:
        v = float(pm.group(1).replace(",", "."))
        minutes = int(v * 60) if pm.group(2).lower().startswith(("h", "час", "ч")) else int(v)
        body = body[:pm.start()] + body[pm.end():]
    at = "18:00"
    am = STUDY_AT_RX.search(body)
    if am:
        hh, mm = am.group(1) or am.group(3), am.group(2) or am.group(4) or "0"
        if int(hh) <= 23 and int(mm) <= 59:
            at = f"{int(hh):02d}:{int(mm):02d}"
            body = body[:am.start()] + body[am.end():]
    topics = [t.strip(" ,.;:-") for t in re.split(r"[,;\n]|\s+и\s+|\s+and\s+", body) if t.strip(" ,.;:-")]
    subject = re.sub(r"(?i)^(?:тест|изпит|контролно|класна работа|матура|test|exam|quiz)\s*(?:по|:)?\s*", "", ex["title"])
    try:
        plan, _ = study_plan(subject if subject != ex["title"] else "", ex["when"].date(), topics, minutes, at, bg=bg)
    except ValueError as e:
        return (f"Не успях да направя план: {e}." if bg else f"I could not make the plan: {e}.")
    return plan_text(plan, minutes, at, bg)


# ---------------------------------------------------------------- birthdays, name days, anniversaries

def yearly(request: str, bg: bool, today: date | None = None) -> str | None:
    today = today or date.today()
    for rx, kind in ((BDAY_RX, "birthday"), (NAMEDAY_RX, "nameday"), (ANNIV_RX, "anniversary")):
        m = rx.match(request)
        if not m:
            continue
        groups = [g for g in m.groups()[:-1] if g]
        who = _owner(groups[0], bg) if groups else ""
        d = _next_yearly(m.groups()[-1], today)
        if not d or (kind != "anniversary" and not who):
            return None
        if kind == "birthday":
            title = f"Рожден ден: {who}" if bg else f"Birthday: {who}"
        elif kind == "nameday":
            title = f"Имен ден: {who}" if bg else f"Name day: {who}"
        else:
            title = (f"Годишнина: {who}" if who else "Нашата годишнина") if bg else (f"Anniversary: {who}" if who else "Our anniversary")
        _add_yearly(title, d)
        months = ["януари", "февруари", "март", "април", "май", "юни", "юли", "август", "септември", "октомври", "ноември", "декември"]
        when = f"{d.day} {months[d.month - 1]}" if bg else d.strftime("%d %B").lstrip("0")
        return (f"Записах: {title} - {when}, всяка година. Ще ти напомням ден по-рано в 9:00, за да имаш време за подарък."
                if bg else f"Saved: {title} - {when}, every year. I will remind you the day before at 9:00, so there is time for a gift.")
    return None


def forgot(request: str, bg: bool, today: date | None = None) -> str | None:
    m = FORGOT_RX.match(request)
    if not m:
        return None
    who = _owner(m.group(1) or m.group(2) or m.group(3) or "", bg)
    tail = (m.group(4) or "").lower()
    today = today or date.today()
    if re.search(r"вчера|yesterday", tail):
        d = today - timedelta(days=1)
    elif re.search(r"днес|today", tail):
        d = today
    elif FEB29_RX.search(tail):
        d = _safe_date(today.year, 2, 29)
    else:
        from . import bills as B

        d, _ = B.find_date(tail, today)
    if not who:
        return None
    if not d:
        return (f"Кога е рожденият ден на {who}? Кажи датата и ще го запиша, за да ти напомням всяка година ден по-рано."
                if bg else f"When is {who}'s birthday? Tell me the date and I will remind you every year, a day before.")
    nxt = _safe_date(today.year, d.month, d.day)
    if nxt <= today:
        nxt = _safe_date(today.year + 1, d.month, d.day)
    _add_yearly(f"Рожден ден: {who}" if bg else f"Birthday: {who}", nxt)
    return (f"Записах рождения ден на {who} - от догодина ще ти напомням ден по-рано в 9:00. Ако искаш, ще ти напиша кратко "
            f"съобщение със закъснял поздрав и извинение - кажи с какъв тон (топло, весело, официално)."
            if bg else f"I saved {who}'s birthday - from next year I will remind you the day before at 9:00. If you like, I will "
            f"write a short belated-birthday message with an apology - just say the tone (warm, funny, formal).")


def answer(request: str, bg: bool) -> str | None:
    """The life events intents.detect tries before the calendar. They all WRITE, so a question is never one of them
    ("Влизат ли дробите в изпита?" must not make a study plan)."""
    from .intents import asks

    if asks(request):
        return None
    for fn in (exam, study, yearly, forgot):
        out = fn(request, bg)
        if out:
            return out
    return None
