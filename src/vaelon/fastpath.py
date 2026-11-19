"""Instant, deterministic answers for trivial requests - no language model, no mistakes, no waiting.

Small local models are slow and unreliable at things a computer simply knows (time, date, RAM).
"""
from __future__ import annotations

import re
import time

BG_DAYS = ["понеделник", "вторник", "сряда", "четвъртък", "петък", "събота", "неделя"]
BG_MONTHS = ["януари", "февруари", "март", "април", "май", "юни", "юли", "август", "септември", "октомври", "ноември", "декември"]
EN_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# the WHOLE question must be about the clock ("What time is my meeting?" is not): optional "now / сега / today" + "?"
_END = r"(?:\s+(?:е|сме|is\s+it|is|it\s+is|now|right\s+now|сега|днес|today|please|моля))*\s*[?.!]*\s*$"
TIME_RX = re.compile(r"(?i)^\s*(?:hey\s+|вейлон,?\s+|vaelon,?\s+)?(колко\s+(е\s+)?(е\s+)?час(а|ът)?|кой\s+час|кое\s+време\s+е|какъв\s+е\s+часът|what('?s| is)?\s+the\s+time|what\s+time|current\s+time)" + _END)
DATE_RX = re.compile(r"(?i)^\s*(?:hey\s+|вейлон,?\s+|vaelon,?\s+)?(коя\s+(е\s+)?(днешната\s+)?дата|какво\s+число|кой\s+ден|коя\s+е\s+датата|what('?s| is)?\s+(the\s+)?(today'?s\s+)?date|what\s+day|today'?s\s+date)" + _END)
SYS_RX = re.compile(r"(?i)\b(колко\s+(е\s+)?(свободн\w+\s+)?(ram|рам|памет)|натоварване\s+на\s+(cpu|процесор)|how\s+much\s+(free\s+)?(ram|memory))\b")


def _bg(text: str) -> bool:
    return bool(re.search(r"[\u0400-\u04FF]", text))


def try_answer(request: str, now: time.struct_time | None = None) -> str | None:
    if len(request) > 80:  # only short, simple questions
        return None
    t = now or time.localtime()
    bg = _bg(request)
    if TIME_RX.search(request):
        hhmm = time.strftime("%H:%M", t)
        return f"Часът е {hhmm}." if bg else f"It is {hhmm}."
    if DATE_RX.search(request):
        if bg:
            return f"Днес е {BG_DAYS[t.tm_wday]}, {t.tm_mday} {BG_MONTHS[t.tm_mon - 1]} {t.tm_year} г."
        return f"Today is {EN_DAYS[t.tm_wday]}, {time.strftime('%d %B %Y', t)}."
    if SYS_RX.search(request):
        try:
            import psutil

            m = psutil.virtual_memory()
            free, total = m.available / 2**30, m.total / 2**30
            return (f"Свободна памет: {free:.1f} от {total:.1f} GB ({m.percent:.0f}% използвана)." if bg
                    else f"Free memory: {free:.1f} of {total:.1f} GB ({m.percent:.0f}% used).")
        except ImportError:
            return None
    return None
