"""Bills and invoices: what you have to pay, what you have paid, and the invoices you issue.

    "добави сметка за ток 45,20 евро до 25.11"   "платих тока"   "какви сметки имам за плащане?"
    "add a bill: internet 25 EUR due 30.11"     "I paid the water bill"   "who owes me?"

Bills to pay: who, how much, by when, a category (guessed from the words: electricity, water, rent ...), the bill's
number, notes, a repeat (monthly / quarterly / yearly - when one is paid the next one is added with the same amount,
marked as an estimate until the real bill comes) and a reminder N days before the due date (default 3), again on the
day and once more when it is overdue. A bill can also be read from a PDF / Word file or a photo (`scan`).
Invoices you issue: numbered in one unbroken 10-digit series (as Bulgarian law asks), seller = "my business",
items, VAT, a due date; the PDF is made on this computer. An issued invoice is never deleted - it can be voided,
and its number stays used.

VAELON NEVER PAYS ANYTHING. It keeps the list and reminds you; paying is always done by you, in your bank.
Everything is stored ENCRYPTED in ~/.vaelon/bills.enc (vault, AES-256-GCM): amounts, names and addresses are private.
Money is kept in cents (whole numbers), never in floating point.
"""
from __future__ import annotations

import calendar as _cal
import json
import re
import threading
import uuid
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from . import config
from .security import vault

FILE = "bills.enc"
REPEATS = ("", "monthly", "quarterly", "yearly")
CURRENCIES = ("EUR", "USD", "GBP", "CHF")  # no BGN: Bulgaria pays in euro since 2026 - leva said or typed are converted
BGN_PER_EUR = Decimal("1.95583")  # the fixed rate (Bulgaria joined the euro on 1 January 2026)
_lock = threading.Lock()

# category -> words that point to it (vendor names included). Checked in this order; the first hit wins.
CATEGORIES = {
    "electricity": r"ток\b|тока\b|електр|енерго|евн\b|evn\b|чез\b|cez\b|електрохолд|energo|electric|power bill",
    "water": r"вода\b|водата\b|вик\b|в и к\b|water\b|water bill",
    "heating": r"парно|топлофикац|отоплен|газ\b|газта\b|heating|district heat|gas\b",
    "internet & phone": r"интернет|телефон|мобил|vivacom|виваком|yettel|йетел|теленор|\ba1\b|булсат|bulsat|internet|"
                        r"phone|mobile|broadband",
    "rent": r"наем|наема|rent\b|rental",
    "insurance": r"застрах|insurance",
    "taxes & fees": r"данък|данъци|нап\b|такса смет|местни такси|tax\b|taxes\b|council\b",
    "subscriptions": r"абонамент|хостинг|домейн|софтуер|netflix|spotify|youtube|hbo\b|disney|apple\b|google one|icloud|"
                     r"subscription|hosting|domain|software|saas",
    "loan": r"кредит|заем|вноска|лизинг|loan|mortgage|instal?lment|leasing",
    "supplier": r"доставчик|стока\b|стоки\b|материали|supplier|stock\b|materials",
    "other": r"$^",
}
CATEGORY_NAMES = tuple(CATEGORIES)
_BG_CATEGORY = {"electricity": "ток", "water": "вода", "heating": "парно", "internet & phone": "интернет и телефон",
                "rent": "наем", "insurance": "застраховка", "taxes & fees": "данъци и такси",
                "subscriptions": "абонаменти", "loan": "кредит", "supplier": "доставчик", "other": "друго"}
# what a known vendor is called when only the category is said ("платих тока" -> the electricity bill)
_BG_MONTHS = ["януари", "февруари", "март", "април", "май", "юни", "юли", "август", "септември", "октомври",
              "ноември", "декември"]


# ---------------------------------------------------------------- storage

def _path() -> Path:
    from . import company  # each company keeps its own money files (the personal workspace: ~/.vaelon as before)

    return company.data_dir() / FILE


def _empty() -> dict:
    return {"bills": [], "invoices": [], "me": {}, "next": 1}


def load(strict: bool = False) -> dict:
    """Everything stored. `strict` (used before every write): a file that exists but cannot be read raises instead of
    looking empty - otherwise the next write would replace all bills and invoices with nothing."""
    p = _path()
    if not p.exists():
        return _empty()
    try:
        data = json.loads(vault.decrypt_text(p.read_text("utf-8").strip()))
    except Exception:
        if strict:
            raise RuntimeError(f"{FILE} could not be read, so nothing was changed (the file is left as it is)")
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    base = _empty()
    base.update({k: v for k, v in data.items() if k in base})
    return base


def _store(data: dict) -> None:
    _path().parent.mkdir(parents=True, exist_ok=True)
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(vault.encrypt_text(json.dumps(data, ensure_ascii=False)), "utf-8")
    vault.replace(tmp, _path())


def _change(fn):
    """Run fn(data) under the lock and store the result. Returns what fn returned."""
    with _lock:
        data = load(strict=True)
        out = fn(data)
        _store(data)
        return out


def snapshot() -> dict:
    """A deep copy of everything (for undo)."""
    return json.loads(json.dumps(load(strict=True)))


def restore_all(data: dict) -> None:
    """Undo: the bills and the business details go back to the snapshot - but an invoice is NEVER taken back (the
    numbering must stay unbroken and a number is never issued twice): invoices made since are kept, the counter only
    moves forward. Taking back an invoice means voiding it."""
    with _lock:
        now = load(strict=True)
        data = json.loads(json.dumps(data))
        have = {i["id"] for i in data.get("invoices", [])}
        data["invoices"] = data.get("invoices", []) + [i for i in now.get("invoices", []) if i["id"] not in have]
        current = {i["id"]: i for i in now.get("invoices", [])}
        data["invoices"] = [current.get(i["id"], i) if i.get("status") == "void" or current.get(i["id"], {}).get("status") == "void"
                            else i for i in data["invoices"]]
        data["next"] = max(int(data.get("next") or 1), int(now.get("next") or 1))
        _store(data)


# ---------------------------------------------------------------- money

def cents(value) -> int:
    """'45,20' / '1 234.56' / 45.2 / Decimal -> 4520. Raises ValueError."""
    if isinstance(value, (int, float, Decimal)):
        d = Decimal(str(value))
    else:
        s = str(value).strip().replace(" ", " ").replace(" ", "")
        s = re.sub(r"[^\d.,-]", "", s).rstrip(".,")  # "45,20 лв." - the dot of the abbreviation is not a separator
        if not re.search(r"\d", s):
            raise ValueError("no amount")
        if "," in s and "." in s:  # both: the last one is the decimal separator
            dec, other = (",", ".") if s.rfind(",") > s.rfind(".") else (".", ",")
            s = s.replace(other, "").replace(dec, ".")
        else:
            sep = "," if "," in s else "." if "." in s else ""
            if sep:
                whole, _, frac = s.rpartition(sep)
                # money has two decimals: "1,234" / "1.234.567" are thousands, "45,20" / "45.5" are decimals
                if s.count(sep) > 1 or (len(frac) == 3 and whole not in ("", "0")):
                    s = s.replace(sep, "")
                else:
                    s = s.replace(sep, ".")
        try:
            d = Decimal(s)
        except InvalidOperation:
            raise ValueError("not an amount")
    c = int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if c < 0 or c > 10**13:
        raise ValueError("the amount is out of range")
    return c


def money(c: int, currency: str = "EUR", bg: bool = False) -> str:
    """4520, 'EUR' -> '45.20 EUR' (Bulgarian: '45,20 евро' - also what the voice reads; old leva records: 'лв.')."""
    whole, frac = divmod(abs(int(c)), 100)
    sep, group = (",", " ") if bg else (".", ",")
    txt = f"{whole:,}".replace(",", group) + f"{sep}{frac:02d}"
    cur = ("евро" if currency == "EUR" else "лв." if currency == "BGN" else currency) if bg else currency
    return ("-" if c < 0 else "") + f"{txt} {cur}"


_CUR_WORDS = [("EUR", r"€|eur|euro|euros|евро|евра"), ("BGN", r"лв\.?|лева|лев|bgn|leva"), ("USD", r"\$|usd|долара?|dollars?"),
              ("GBP", r"£|gbp|паунда?|pounds?"), ("CHF", r"chf|франка?")]
_CUR_ALT = "|".join(w for _, w in _CUR_WORDS)
_NUM = r"\d{1,3}(?:[  ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?(?!\d)"
AMOUNT_RX = re.compile(r"(?i)(?:(?<![\w])(" + _CUR_ALT + r")\s*(" + _NUM + r"))|(?:(?<![\d.,])(" + _NUM + r")\s*(" + _CUR_ALT + r")(?![\w]))")
BARE_RX = re.compile(r"(?<![\d.,:/\w-])(" + _NUM + r")(?![\d.,:/]?\d)")


def currency_of(word: str) -> str:
    low = (word or "").lower().strip()
    return next((code for code, rx in _CUR_WORDS if re.fullmatch(rx, low)), "EUR")


def euro_first(c: int, currency: str) -> tuple[int, str]:
    """Leva -> euro at the fixed rate (1 EUR = 1.95583 BGN); every other currency stays as it is."""
    return (to_eur(c, "BGN"), "EUR") if currency == "BGN" else (c, currency)


def find_amount(text: str, default_currency: str = "EUR") -> tuple[int, str, str] | None:
    """The first amount in a phrase -> (cents, currency, the phrase without it). Dates must be removed first.
    An amount in leva comes back in euro (converted at the fixed rate)."""
    m = AMOUNT_RX.search(text)
    if m:
        cur_word, num = (m.group(1), m.group(2)) if m.group(2) else (m.group(4), m.group(3))
        c, cur = euro_first(cents(num), currency_of(cur_word))
        return c, cur, (text[:m.start()] + " " + text[m.end():]).strip()
    m = BARE_RX.search(text)
    if m:
        return cents(m.group(1)), default_currency, (text[:m.start()] + " " + text[m.end():]).strip()
    return None


def to_eur(c: int, currency: str) -> int | None:
    if currency == "EUR":
        return c
    if currency == "BGN":
        return int((Decimal(c) / BGN_PER_EUR).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return None


# ---------------------------------------------------------------- dates

_MONTHS = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
           "september": 9, "october": 10, "november": 11, "december": 12, "jan": 1, "feb": 2, "mar": 3, "apr": 4,
           "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
           **{m: i for i, m in enumerate(_BG_MONTHS, 1)}}
_MON_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))
_LEAD = r"(?:(?:due|by|until|before|on|pay by|payable by|до|на|срок(?: за плащане)?|падеж|платима до|за плащане до)\s+)?"
DATE_RXS = [
    re.compile(r"(?i)" + _LEAD + r"(?<![\d.])(\d{4})-(\d{2})-(\d{2})(?!\d)"),
    re.compile(r"(?i)" + _LEAD + r"(?<![\d.,])(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?(?:\s*г\.?)?(?![\d,]|\.\d)(?!\s*(?:" + _CUR_ALT + r")(?![\w]))"
               r"(?!\s*(?:кг|kg|литра?|л\b|l\b|куб|м3|m3|км|km|ч\b|h\b|%|x\b|бр|pcs|kwh|квтч|mb|gb|ml|мл))"),
    re.compile(r"(?i)" + _LEAD + r"(?<!\d)(\d{1,2})(?:st|nd|rd|th|-?ти|-?ри|-?ви)?\s+(" + _MON_ALT + r")(?:\s+(\d{4}))?(?![\w])"),
    re.compile(r"(?i)" + _LEAD + r"(?<![\w])(" + _MON_ALT + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?(?![\w])"),
]
REL_RX = re.compile(r"(?i)(?:(?:due|by|до|за)\s+)?(?:(today|днес)|(tomorrow|утре)|(?:in|след)\s+(\d{1,3})\s*(?:days?|дни|дена|ден))(?![\w])")


def find_date(text: str, today: date | None = None) -> tuple[date | None, str]:
    """A date in a phrase -> (date, the phrase without it). '25.11', '2026-11-25', '25 ноември', 'November 25',
    'до 25.11.2026', 'tomorrow', 'in 10 days'. A day.month without a year is this year (or next year if that is
    more than half a year ago)."""
    today = today or date.today()
    for n, rx in enumerate(DATE_RXS):
        m = rx.search(text)
        if not m:
            continue
        g = m.groups()
        try:
            if n == 0:
                y, mo, d = int(g[0]), int(g[1]), int(g[2])
            elif n == 1:
                d, mo, y = int(g[0]), int(g[1]), int(g[2]) if g[2] else None
            elif n == 2:
                d, mo, y = int(g[0]), _MONTHS[g[1].lower()], int(g[2]) if g[2] else None
            else:
                mo, d, y = _MONTHS[g[0].lower()], int(g[1]), int(g[2]) if g[2] else None
            if y is not None and y < 100:
                y += 2000
            if y is None:
                y = today.year
                if date(y, mo, d) < today - timedelta(days=183):
                    y += 1
            found = date(y, mo, d)
        except (ValueError, KeyError):
            continue
        return found, re.sub(r"\s+", " ", text[:m.start()] + " " + text[m.end():]).strip()
    m = REL_RX.search(text)
    if m:
        found = today if m.group(1) else today + timedelta(days=1 if m.group(2) else int(m.group(3)))
        return found, re.sub(r"\s+", " ", text[:m.start()] + " " + text[m.end():]).strip()
    return None, text


def _shift(d: date, repeat: str, day: int | None = None) -> date:
    months = {"monthly": 1, "quarterly": 3, "yearly": 12}.get(repeat, 0)
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    return d.replace(year=y, month=m, day=min(day or d.day, _cal.monthrange(y, m)[1]))


def day_text(d: date, bg: bool, today: date | None = None) -> str:
    today = today or date.today()
    diff = (d - today).days
    if diff == 0:
        return "днес" if bg else "today"
    if diff == 1:
        return "утре" if bg else "tomorrow"
    if diff == -1:
        return "вчера" if bg else "yesterday"
    return f"{d.day} {_BG_MONTHS[d.month - 1]}" + (f" {d.year}" if d.year != today.year else "") if bg else \
        d.strftime("%d %B").lstrip("0") + (f" {d.year}" if d.year != today.year else "")


def period(text: str, today: date | None = None) -> tuple[date, date, str]:
    """'this month' / 'last month' / 'this year' / 'last year' / '2026' / 'ноември' -> [from, to) and a label.
    Default: this year."""
    today = today or date.today()
    low = (text or "").lower()
    first = today.replace(day=1)
    if re.search(r"last month|миналия месец|предния месец", low):
        prev = (first - timedelta(days=1)).replace(day=1)
        return prev, first, prev.strftime("%B %Y")
    if re.search(r"month|месец", low):
        return first, _shift(first, "monthly"), first.strftime("%B %Y")
    if re.search(r"last year|миналата година|предната година", low):
        return date(today.year - 1, 1, 1), date(today.year, 1, 1), str(today.year - 1)
    m = re.search(r"(?<!\d)(20\d\d)(?!\d)", low)
    if m:
        y = int(m.group(1))
        return date(y, 1, 1), date(y + 1, 1, 1), str(y)
    m = re.search(r"(?i)(?<![\w])(" + _MON_ALT + r")(?![\w])", low)
    if m:
        mo = _MONTHS[m.group(1)]
        y = today.year if mo <= today.month else today.year - 1
        start = date(y, mo, 1)
        return start, _shift(start, "monthly"), start.strftime("%B %Y")
    if re.search(r"all|everything|всичк|цялото", low):
        return date(2000, 1, 1), date(2100, 1, 1), "all time"
    return date(today.year, 1, 1), date(today.year + 1, 1, 1), str(today.year)


# ---------------------------------------------------------------- words -> fields

def category_of(text: str) -> str:
    low = (text or "").lower()
    if low.strip() in CATEGORIES:
        return low.strip()
    for name, rx in CATEGORIES.items():
        if re.search(r"(?i)(?<![\w])(?:" + rx + r")", low):
            return name
    return "other"


def category_label(name: str, bg: bool) -> str:
    return _BG_CATEGORY.get(name, name) if bg else name


def _clean_vendor(text: str) -> str:
    v = re.sub(r"(?i)^(?:(?:please|add|put|save|record|моля|добави|запиши|сложи)\s+)+", "", text.strip(" ,.:;-"))
    v = re.sub(r"(?i)^(?:(?:a|an|the|new|my)\s+)*(?:bill|invoice|payment)s?\b\s*(?:for|from|of|to|:|-)?\s*", "", v)
    v = re.sub(r"(?i)^(?:нова\s+)?(?:сметка|сметката|сметки|фактура|фактурата|плащане)\s*(?:за|от|към|на|:|-)?\s*", "", v)
    v = re.sub(r"(?i)^(?:за|for|from|от|към|of|to)\s+", "", v.strip(" ,.:;-"))
    v = re.sub(r"(?i)(?:\s+(?:due|by|until|on|for|до|на|за|от|срок|падеж))+$", "", v.strip(" ,.:;-"))
    v = re.sub(r"\s+", " ", v).strip(" ,.:;-")
    return v[:1].upper() + v[1:] if v else ""


def repeat_of(text: str) -> str:
    low = str(text or "").lower().strip()
    if low in REPEATS:
        return low
    for name, rx in (("monthly", r"monthly|every month|each month|всеки месец|ежемесечн|месечн"),
                     ("quarterly", r"quarterly|every (?:3|three) months|всяко тримесечие|на 3 месеца|тримесечн"),
                     ("yearly", r"yearly|annual|every year|всяка година|годишн|ежегодн")):
        if re.search(rx, low):
            return name
    return ""


# ---------------------------------------------------------------- bills to pay

def _bill(vendor: str, amount: int, currency: str, due: date | None, category: str, number: str, notes: str,
          repeat: str, remind: int | None, estimate: bool = False, file: str = "") -> dict:
    vendor = re.sub(r"\s+", " ", str(vendor)).strip()[:120]
    if not vendor:
        raise ValueError("say who the bill is from (e.g. electricity, rent, the company's name)")
    if currency not in CURRENCIES:
        raise ValueError("currency must be one of " + ", ".join(CURRENCIES))
    if repeat not in REPEATS:
        raise ValueError("repeat must be monthly, quarterly or yearly")
    if category not in CATEGORIES:
        category = category_of(category + " " + vendor)
    return {"id": uuid.uuid4().hex[:6], "vendor": vendor, "amount": int(amount), "currency": currency,
            "due": due.isoformat() if due else "", "category": category, "number": str(number).strip()[:40],
            "notes": str(notes).strip()[:500], "status": "unpaid", "paid_on": "", "repeat": repeat,
            "remind": None if remind is None else max(0, min(60, int(remind))), "alerted": "", "estimate": estimate,
            "file": str(file)[:400], "added": date.today().isoformat()}


def add_bill(vendor: str, amount: int, currency: str = "EUR", due: date | None = None, category: str = "",
             number: str = "", notes: str = "", repeat: str = "", remind: int | None = 3, file: str = "") -> dict:
    """Add a bill. A real bill replaces the estimate made for the same vendor's next payment."""
    amount, currency = euro_first(amount, currency)
    b = _bill(vendor, amount, currency, due, category or category_of(vendor + " " + notes), number, notes, repeat,
              remind, file=file)

    def go(data):
        for old in data["bills"]:
            if (old.get("estimate") and old["status"] == "unpaid" and old["vendor"].lower() == b["vendor"].lower()
                    and (not b["due"] or not old["due"] or abs((date.fromisoformat(old["due"]) - date.fromisoformat(b["due"])).days) <= 25)):
                b["repeat"] = b["repeat"] or old["repeat"]
                data["bills"].remove(old)
                break
        data["bills"].append(b)
        return b

    return _change(go)


def get_bill(bid: str) -> dict | None:
    return next((b for b in load()["bills"] if b["id"] == bid), None)


def update_bill(bid: str, **changes) -> dict | None:
    def go(data):
        for b in data["bills"]:
            if b["id"] == bid:
                b.update(changes)
                return dict(b)
        return None

    return _change(go)


def delete_bill(bid: str) -> dict | None:
    def go(data):
        gone = next((b for b in data["bills"] if b["id"] == bid), None)
        if gone:
            data["bills"].remove(gone)
        return gone

    return _change(go)


def mark_paid(bid: str, on: date | None = None) -> tuple[dict, dict | None] | None:
    """Mark a bill paid. For a repeating bill the next one is added (same amount, an estimate). Returns (bill, next)."""
    on = on or date.today()

    def go(data):
        b = next((x for x in data["bills"] if x["id"] == bid), None)
        if not b:
            return None
        if b.get("status") == "paid":  # a second "paid" (a double click) adds no second next bill
            return dict(b), None
        b["status"], b["paid_on"] = "paid", on.isoformat()
        nxt = None
        if b.get("repeat"):
            base = date.fromisoformat(b["due"]) if b["due"] else on
            day = int(b.get("day") or base.day)  # the bill's own day: 31.01 -> 28.02 -> 31.03, never stuck on the 28th
            nxt = _bill(b["vendor"], b["amount"], b["currency"], _shift(base, b["repeat"], day), b["category"], "",
                        b.get("notes", ""), b["repeat"], b.get("remind"), estimate=True)
            nxt["day"] = day
            if b.get("file") or b.get("src"):
                nxt["src"] = "file"  # its vendor and notes came from that file (registry.outside_shown)
            data["bills"].append(nxt)
        return dict(b), nxt

    return _change(go)


def mark_unpaid(bid: str) -> dict | None:
    """Undo a 'paid' (and remove the estimate that it created, if that is still untouched)."""
    def go(data):
        b = next((x for x in data["bills"] if x["id"] == bid), None)
        if not b:
            return None
        if b.get("repeat") and b["status"] == "paid":
            base = date.fromisoformat(b["due"]) if b["due"] else date.fromisoformat(b["paid_on"] or date.today().isoformat())
            nd = _shift(base, b["repeat"]).isoformat()
            for x in list(data["bills"]):
                if x.get("estimate") and x["status"] == "unpaid" and x["vendor"] == b["vendor"] and x["due"] == nd:
                    data["bills"].remove(x)
                    break
        b["status"], b["paid_on"] = "unpaid", ""
        return dict(b)

    return _change(go)


def unpaid(today: date | None = None) -> list[dict]:
    """Unpaid bills: overdue first, then by due date; bills without a date last."""
    return sorted((b for b in load()["bills"] if b["status"] == "unpaid"),
                  key=lambda b: (b["due"] == "", b["due"], b["vendor"].lower()))


def match(words: str, status: str = "unpaid") -> list[dict]:
    """Bills whose vendor, category, number or notes fit the words ('тока', 'the water bill', 'EVN')."""
    low = (words or "").lower()
    cat = category_of(low)
    terms = [t for t in re.findall(r"[\wа-я]{3,}", low) if t not in
             {"bill", "bills", "the", "for", "paid", "сметка", "сметката", "сметки", "платих", "за", "the", "invoice", "фактура",
              "фактурата", "mark", "отбележи", "като", "платена", "платени"}]
    out = []
    for b in load()["bills"]:
        if status and b["status"] != status:
            continue
        hay = " ".join([b["vendor"], b.get("number", ""), b.get("notes", "")]).lower()
        if (cat != "other" and b["category"] == cat) or any(t in hay for t in terms):
            out.append(b)
    return sorted(out, key=lambda b: (b["due"] == "", b["due"]))


def bill_line(b: dict, bg: bool, ids: bool = True, today: date | None = None) -> str:
    today = today or date.today()
    amount = ("~" if b.get("estimate") else "") + money(b["amount"], b["currency"], bg)
    when = ""
    if b["status"] == "paid":
        when = (f"платена {day_text(date.fromisoformat(b['paid_on']), bg, today)}" if bg
                else f"paid {day_text(date.fromisoformat(b['paid_on']), bg, today)}") if b.get("paid_on") else ""
    elif b["due"]:
        d = date.fromisoformat(b["due"])
        if d < today:
            when = f"ПРОСРОЧЕНА от {day_text(d, bg, today)}" if bg else f"OVERDUE since {day_text(d, bg, today)}"
        else:
            when = f"до {day_text(d, bg, today)}" if bg else f"due {day_text(d, bg, today)}"
    cat = category_label(b["category"], bg)
    extra = f" ({cat})" if cat.lower() not in b["vendor"].lower() and b["category"] != "other" else ""
    rep = {"monthly": " ↻ месечно" if bg else " ↻ monthly", "quarterly": " ↻ на 3 месеца" if bg else " ↻ quarterly",
           "yearly": " ↻ годишно" if bg else " ↻ yearly"}.get(b.get("repeat", ""), "")
    num = f", {'№' if bg else 'no.'} {b['number']}" if b.get("number") else ""
    return (f"{b['vendor']}{extra}: {amount}" + (f" - {when}" if when else "") + num + rep
            + (f"  [id {b['id']}]" if ids else ""))


def totals(bills: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for b in bills:
        out[b["currency"]] = out.get(b["currency"], 0) + b["amount"]
    return out


def totals_text(t: dict[str, int], bg: bool) -> str:
    return " + ".join(money(c, cur, bg) for cur, c in sorted(t.items())) or money(0, "EUR", bg)


def unpaid_text(bg: bool, ids: bool = True, today: date | None = None) -> str:
    today = today or date.today()
    items = unpaid(today)
    if not items:
        return "Нямаш неплатени сметки." if bg else "You have no unpaid bills."
    late = [b for b in items if b["due"] and date.fromisoformat(b["due"]) < today]
    head = (f"Неплатени сметки ({len(items)}), общо {totals_text(totals(items), bg)}" if bg
            else f"Unpaid bills ({len(items)}), {totals_text(totals(items), bg)} in total")
    if late:
        head += (f"; просрочени: {len(late)}" if bg else f"; overdue: {len(late)}")
    lines = [head + ":"] + ["• " + bill_line(b, bg, ids, today) for b in items[:30]]
    if any(b.get("estimate") for b in items):
        lines.append("(~ = очаквана сума, докато дойде истинската сметка)" if bg else "(~ = expected amount until the real bill arrives)")
    return "\n".join(lines)


def summary(frm: date, to: date, label: str, bg: bool) -> str:
    """What was paid in [frm, to) by category, what is still open, and the invoices issued in that time."""
    data = load()
    paid = [b for b in data["bills"] if b["status"] == "paid" and b.get("paid_on") and frm <= date.fromisoformat(b["paid_on"]) < to]
    lines = [(f"Платени сметки за {label}: {totals_text(totals(paid), bg)}" if bg
              else f"Bills paid in {label}: {totals_text(totals(paid), bg)}")]
    by_cat: dict[str, list[dict]] = {}
    for b in paid:
        by_cat.setdefault(b["category"], []).append(b)
    for cat, items in sorted(by_cat.items(), key=lambda kv: -sum(to_eur(b["amount"], b["currency"]) or b["amount"] for b in kv[1])):
        lines.append(f"• {category_label(cat, bg)}: {totals_text(totals(items), bg)} ({len(items)})")
    open_ = [b for b in data["bills"] if b["status"] == "unpaid"]
    if open_:
        lines.append((f"Още за плащане: {totals_text(totals(open_), bg)} ({len(open_)})" if bg
                      else f"Still to pay: {totals_text(totals(open_), bg)} ({len(open_)})"))
    inv = [i for i in data["invoices"] if i["status"] != "void" and frm <= date.fromisoformat(i["issued"]) < to]
    if inv:
        got = [i for i in inv if i["status"] == "paid"]
        owed = [i for i in inv if i["status"] == "unpaid"]
        t_all = {}
        for i in inv:
            t_all[i["currency"]] = t_all.get(i["currency"], 0) + invoice_totals(i)[2]
        lines.append((f"Издадени фактури: {len(inv)}, общо {totals_text(t_all, bg)}; платени {len(got)}, чакат плащане {len(owed)}"
                      if bg else f"Invoices issued: {len(inv)}, {totals_text(t_all, bg)} in total; paid {len(got)}, waiting {len(owed)}"))
    return "\n".join(lines)


# ---------------------------------------------------------------- reminders

def fire_due(now: datetime | None = None, toast: bool = True) -> list[str]:
    """Remind about unpaid bills: `remind` days before the due date, on the day, and once when overdue.
    Only between 08:00 and 21:59, each stage once. Called by the reminder thread (reminders.watch)."""
    from . import reminders

    now = now or datetime.now()
    if not 8 <= now.hour < 22:
        return []
    today = now.date()
    fired = []
    with _lock:
        data, changed = load(strict=True), False
        for b in data["bills"]:
            if b["status"] != "unpaid" or not b["due"] or b.get("remind") is None:
                continue
            due = date.fromisoformat(b["due"])
            stage = ("late" if today > due else "due" if today == due
                     else "before" if today >= due - timedelta(days=b["remind"]) else "")
            key = f"{b['due']}:{stage}"
            done = b.get("alerted", "")
            rank = {"": 0, "before": 1, "due": 2, "late": 3}
            if not stage or (done.startswith(b["due"] + ":") and rank[done.split(":")[1]] >= rank[stage]):
                continue
            b["alerted"], changed = key, True
            amount = ("~" if b.get("estimate") else "") + money(b["amount"], b["currency"])
            text = {"before": f"{b['vendor']}: {amount} is due {day_text(due, False, today)}",
                    "due": f"{b['vendor']}: {amount} is due TODAY",
                    "late": f"{b['vendor']}: {amount} is OVERDUE (was due {day_text(due, False, today)})"}[stage]
            fired.append(text)
        if changed:
            _store(data)
    for text in fired:
        reminders.notify("Vaelon - bill", text, "reminder", toast)
    return fired


# ---------------------------------------------------------------- reading a bill (PDF, Word, a photo's text)

_TOTAL_WORDS = [r"обща сума за плащане", r"сума за плащане", r"общо за плащане", r"дължима сума", r"за плащане",
                r"сума с ддс", r"всичко", r"общо", r"amount due", r"total due", r"balance due", r"total amount",
                r"amount payable", r"to pay", r"grand total", r"total"]
_DUE_WORDS = r"срок за плащане|краен срок|падеж|платима до|плащане до|дата на падеж|due date|payment due|pay by|due by|due"
_NUMBER_RX = re.compile(r"(?i)(?:фактура|сметка|invoice|bill|документ)\s*(?:№|no\.?|nr\.?|number|номер|#)\s*[:.]?\s*([A-Z0-9][A-Z0-9/-]{2,24})")
_COMPANY_RX = re.compile(r"(?m)^\s*(?:(?:доставчик|продавач|издател|получател на плащането|supplier|seller|from|vendor)\s*[:\-]\s*)?"
                         r"([\"„«]?[\w\"„“”«».&' -]{2,60}?\s(?:ЕООД|ООД|ЕАД|АД|ЕТ|АДСИЦ|Ltd\.?|LLC|GmbH|Inc\.?|S\.A\.|plc)[\"”»]?)\b")
_SELLER_RX = re.compile(r"(?im)^\s*(?:доставчик|продавач|издател|supplier|seller|vendor|from)\s*[:\-]\s*(.{2,60})$")


def scan(text: str, today: date | None = None) -> dict:
    """Pull the bill's fields out of its text: vendor, amount, currency, due date, number, category.
    Missing fields are left empty - the caller says what could not be read. The text is untrusted: nothing in it
    is followed, it is only searched for these fields."""
    today = today or date.today()
    t = text.replace(" ", " ")
    out: dict = {"vendor": "", "amount": None, "currency": "", "due": None, "number": "", "category": "other"}
    low = t.lower()
    # amount: the line with the strongest "total to pay" word that carries an amount
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    best = None
    for rank, word in enumerate(_TOTAL_WORDS):
        for i, ln in enumerate(lines):
            if re.search(r"(?i)(?<![\w])" + word + r"(?![\w])", ln):
                rest = re.split(r"(?i)" + word, ln, maxsplit=1)[-1]
                for cand in (rest, lines[i + 1] if i + 1 < len(lines) else ""):
                    cand_wo_dates = cand
                    for rx in DATE_RXS:
                        cand_wo_dates = rx.sub(" ", cand_wo_dates)
                    hit = find_amount(cand_wo_dates, "")
                    if hit and hit[0] > 0:
                        best = hit
                        break
                if best:
                    break
        if best:
            break
    if not best:  # no label: the largest amount that names a currency
        found = []
        for m in AMOUNT_RX.finditer(t):
            try:
                found.append(find_amount(m.group(0), ""))
            except ValueError:
                pass
        found = [f for f in found if f]
        if found:
            best = max(found, key=lambda f: f[0])
    if best:
        out["amount"] = best[0]
        cur = best[1]
        if not cur or not re.search(_CUR_ALT, low):
            cur = "BGN" if re.search(r"лв|лева|bgn", low) else "EUR" if re.search(r"€|eur|евро", low) else (best[1] or "")
        out["amount"], out["currency"] = euro_first(out["amount"], cur or "EUR")
    for m in re.finditer(r"(?i)(?<!total )(?<!amount )(?<!balance )(?:" + _DUE_WORDS + r")\s*[:\-]?\s*(.{0,40})", t):
        d, _ = find_date(m.group(1), today)
        if d:  # "Total due: 24.00" carries no date - the next "Due date: ..." does
            out["due"] = d
            break
    m = _NUMBER_RX.search(t)
    if m:
        out["number"] = m.group(1).strip("-/")
    m = _SELLER_RX.search(t) or _COMPANY_RX.search(t)
    if m:
        out["vendor"] = re.sub(r"\s+", " ", m.group(1)).strip(" \"„“”«»:-")[:80]
    out["category"] = category_of((out["vendor"] + " " + t[:2000]))
    if not out["vendor"] and out["category"] != "other":
        out["vendor"] = category_label(out["category"], False).capitalize()
    return out


# ---------------------------------------------------------------- my business + the invoices I issue

PROFILE_FIELDS = {"name": 120, "address": 200, "company_id": 30, "vat_id": 30, "person": 80, "bank": 300,
                  "email": 120, "phone": 40}


def profile() -> dict:
    return dict(load()["me"])


def set_profile(**fields) -> dict:
    """Seller details printed on invoices. `vat_rate` (percent), `currency`, `next` (the next invoice number) too."""
    def go(data):
        me = data["me"]
        if fields:
            me.pop("demo", None)  # the user filled in real details: removing the demo must keep them
        for k, v in fields.items():
            if k in PROFILE_FIELDS:
                me[k] = re.sub(r"[\r\t]", " ", str(v)).strip()[:PROFILE_FIELDS[k]]
            elif k == "vat_rate":
                rate = Decimal(str(v).replace(",", ".").strip(" %"))
                if not 0 <= rate <= 50:
                    raise ValueError("VAT must be between 0 and 50 %")
                me["vat_rate"] = str(rate.normalize()) if rate != rate.to_integral() else str(int(rate))
            elif k == "currency":
                if str(v).upper() not in CURRENCIES:
                    raise ValueError("currency must be one of " + ", ".join(CURRENCIES))
                me["currency"] = str(v).upper()
            elif k == "next":
                n = int(v)  # only forward (e.g. to continue the series of the program used before)
                used = max([int(i["number"]) for i in data["invoices"] if i["number"].isdigit()] or [0])
                if n <= used:
                    raise ValueError(f"the next number must be above {used} (already used)")
                if n >= 10**10:
                    raise ValueError("an invoice number has at most 10 digits")
                data["next"] = n
            else:
                raise ValueError(f"unknown field: {k}")
        return dict(me)

    return _change(go)


def parse_items(text: str, default_qty: str = "1") -> list[dict]:
    """'Web design | 1 | 500' or 'Hosting 12 x 10' or '2 x Consulting 150' or 'Logo - 300' (one per line or ';').
    -> [{"desc", "qty", "price"}] (qty as a decimal string, price in cents)."""
    parts = [p for p in re.split(r"\n|;", str(text)) if p.strip()]
    out = []
    for p in parts:
        p = p.strip(" ,-•*\t")
        cells = [c.strip() for c in p.split("|")]
        try:
            if len(cells) >= 3:
                desc, qty, price = cells[0], cells[1], cells[2]
            elif len(cells) == 2:
                desc, qty, price = cells[0], default_qty, cells[1]
            else:
                m = (re.match(r"^(\d+(?:[.,]\d+)?)\s*[x×*]\s*(.+?)\s*[-–:@=]?\s*(?:à|@|по|each|бр\.?)?\s*(" + _NUM + r")\s*(?:" + _CUR_ALT + r")?$", p, re.I)
                     or None)
                if m:
                    qty, desc, price = m.group(1), m.group(2), m.group(3)
                else:
                    m = re.match(r"^(.+?)\s+(\d+(?:[.,]\d+)?)\s*[x×*]\s*(" + _NUM + r")\s*(?:" + _CUR_ALT + r")?$", p, re.I)
                    if m:
                        desc, qty, price = m.group(1), m.group(2), m.group(3)
                    else:
                        m = re.match(r"^(.+?)\s*[-–:=]?\s*(" + _NUM + r")\s*(?:" + _CUR_ALT + r")?$", p, re.I)
                        if not m:
                            raise ValueError(f"I could not read the item '{p}'. Use 'description | quantity | price'.")
                        desc, qty, price = m.group(1), default_qty, m.group(2)
            q = Decimal(str(qty).replace(",", ".").strip() or "1")
            if q <= 0 or q > 10**6:
                raise ValueError(f"bad quantity in '{p}'")
            desc = re.sub(r"\s+", " ", desc).strip(" -–:=")[:200]
            if not desc:
                raise ValueError(f"an item needs a description: '{p}'")
            out.append({"desc": desc, "qty": str(q.normalize()) if q != q.to_integral() else str(int(q)), "price": cents(price)})
        except (InvalidOperation, ValueError) as e:
            raise ValueError(str(e) if str(e) else f"I could not read the item '{p}'")
    if not out:
        raise ValueError("the invoice needs at least one item")
    return out[:100]


def invoice_totals(inv: dict) -> tuple[int, int, int]:
    """(net, VAT, total) in cents."""
    net = sum(int((Decimal(it["qty"]) * it["price"]).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) for it in inv["items"])
    vat = int((Decimal(net) * Decimal(inv.get("vat_rate", "0")) / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return net, vat, net + vat


def new_invoice(client: dict, items: list[dict], vat_rate: str | None = None, due_days: int = 14,
                currency: str = "", notes: str = "", lang: str = "bg", issued: date | None = None) -> dict:
    """Number and store a new invoice (the PDF is made by `invoice_pdf`). Needs the seller's name first."""
    client = {k: re.sub(r"\s+", " ", str(client.get(k, ""))).strip()[:PROFILE_FIELDS.get(k, 200)]
              for k in ("name", "address", "company_id", "vat_id", "person", "email")}
    if not client["name"]:
        raise ValueError("the invoice needs the client's name")
    issued = issued or date.today()

    def go(data):
        me = data["me"]
        if not me.get("name"):
            raise ValueError("first fill in your business details (Bills > My business, or say: my business is called ...)")
        rate = vat_rate if vat_rate not in (None, "") else me.get("vat_rate", "20" if me.get("vat_id") else "0")
        rate_d = Decimal(str(rate).replace(",", ".").strip(" %"))
        if not 0 <= rate_d <= 50:
            raise ValueError("VAT must be between 0 and 50 %")
        cur = (currency or me.get("currency") or "EUR").upper()
        if cur not in CURRENCIES:
            raise ValueError("currency must be one of " + ", ".join(CURRENCIES))
        used = {i["number"] for i in data["invoices"]}
        n = int(data.get("next") or 1)
        while f"{n:010d}" in used:
            n += 1
        inv = {"id": uuid.uuid4().hex[:6], "number": f"{n:010d}", "client": client, "items": items,
               "vat_rate": str(rate_d.normalize()) if rate_d != rate_d.to_integral() else str(int(rate_d)),
               "currency": cur, "issued": issued.isoformat(), "due": (issued + timedelta(days=max(0, int(due_days)))).isoformat(),
               "status": "unpaid", "paid_on": "", "notes": str(notes).strip()[:500], "lang": "en" if lang == "en" else "bg",
               "seller": dict(me), "file": ""}
        data["invoices"].append(inv)
        data["next"] = n + 1
        return inv

    return _change(go)


def find_invoice(key: str) -> dict | None:
    key = str(key).strip().lstrip("№#").strip()
    items = load()["invoices"]
    hit = next((i for i in items if i["id"] == key), None)  # the id first (an id can be all digits too)
    if hit or not key.isdigit():
        return hit
    return next((i for i in items if str(i["number"]).isdigit() and int(i["number"]) == int(key)), None)  # DEMO-... skipped


def update_invoice(iid: str, **changes) -> dict | None:
    def go(data):
        for i in data["invoices"]:
            if i["id"] == iid:
                i.update(changes)
                return dict(i)
        return None

    return _change(go)


def owed_text(bg: bool, ids: bool = True, today: date | None = None) -> str:
    today = today or date.today()
    items = sorted((i for i in load()["invoices"] if i["status"] == "unpaid"), key=lambda i: i["due"])
    if not items:
        return "Няма неплатени фактури към теб." if bg else "Nobody owes you anything: no unpaid invoices."
    t: dict[str, int] = {}
    for i in items:
        t[i["currency"]] = t.get(i["currency"], 0) + invoice_totals(i)[2]
    n = len(items)
    lines = [((f"Чака плащане 1 фактура, " if n == 1 else f"Чакат плащане {n} фактури, ") + f"общо {totals_text(t, bg)}:" if bg
              else ("1 invoice is" if n == 1 else f"{n} invoices are") + f" waiting for payment, {totals_text(t, bg)} in total:")]
    for i in items:
        lines.append("• " + invoice_line(i, bg, ids, today))
    return "\n".join(lines)


def invoice_line(i: dict, bg: bool, ids: bool = True, today: date | None = None) -> str:
    today = today or date.today()
    total = money(invoice_totals(i)[2], i["currency"], bg)
    due = date.fromisoformat(i["due"])
    if i["status"] == "paid":
        state = "платена" if bg else "paid"
    elif i["status"] == "void":
        state = "анулирана" if bg else "void"
    elif due < today:
        state = f"ПРОСРОЧЕНА от {day_text(due, bg, today)}" if bg else f"OVERDUE since {day_text(due, bg, today)}"
    else:
        state = f"падеж {day_text(due, bg, today)}" if bg else f"due {day_text(due, bg, today)}"
    return f"{'№' if bg else 'no.'} {i['number']} {i['client']['name']}: {total} - {state}" + (f"  [id {i['id']}]" if ids else "")


# ---------------------------------------------------------------- the invoice as a PDF

_LABELS = {
    "bg": {"title": "ФАКТУРА", "original": "ОРИГИНАЛ", "number": "Номер", "date": "Дата на издаване",
           "tax_date": "Дата на данъчното събитие", "seller": "Доставчик", "buyer": "Получател",
           "company_id": "ЕИК", "vat_id": "ДДС №", "person": "МОЛ", "address": "Адрес", "n": "№", "desc": "Описание",
           "qty": "Кол.", "price": "Ед. цена", "sum": "Стойност", "net": "Данъчна основа", "vat": "ДДС",
           "total": "Сума за плащане", "due": "Срок за плащане", "bank": "Плащане по сметка", "void": "АНУЛИРАНА",
           "no_vat": "Основание за неначисляване на ДДС: чл. 113, ал. 9 от ЗДДС", "made_by": "Съставил",
           "void_note": "Тази фактура е анулирана."},
    "en": {"title": "INVOICE", "original": "ORIGINAL", "number": "Number", "date": "Date of issue",
           "tax_date": "Date of supply", "seller": "Seller", "buyer": "Bill to", "company_id": "Company no.",
           "vat_id": "VAT no.", "person": "Contact", "address": "Address", "n": "#", "desc": "Description",
           "qty": "Qty", "price": "Unit price", "sum": "Amount", "net": "Net", "vat": "VAT", "total": "Total due",
           "due": "Payment due", "bank": "Pay to", "void": "VOID", "no_vat": "No VAT charged.",
           "made_by": "Issued by", "void_note": "This invoice has been voided."},
}


def invoice_pdf(inv: dict, path: Path) -> None:
    """Write the invoice as an A4 PDF (fpdf2, Unicode fonts so Cyrillic works)."""
    import logging

    logging.getLogger("fontTools").setLevel(logging.ERROR)
    try:
        from fpdf import FPDF
    except ImportError:
        raise RuntimeError('PDF files need: pip install "vaelon[docs]"')
    from .tools.create import _pdf_fonts

    L = _LABELS[inv.get("lang", "bg")]
    bg = inv.get("lang", "bg") == "bg"
    seller, client = inv.get("seller") or {}, inv["client"]
    pdf = FPDF(format="A4")
    pdf.set_margins(18, 16, 18)
    pdf.set_auto_page_break(True, 18)
    pdf.set_title(f"{L['title']} {inv['number']}")
    pdf.set_creator("Vaelon")
    fam, _mono = _pdf_fonts(pdf)
    latin = fam == "Helvetica"

    def fix(s) -> str:
        s = str(s).replace("‑", "-").replace(" ", " ")
        return s.encode("latin-1", "replace").decode("latin-1") if latin else s

    def d(iso: str) -> str:
        x = date.fromisoformat(iso)
        return f"{x:%d.%m.%Y}" if bg else f"{x:%d %b %Y}"

    pdf.add_page()
    pdf.set_font(fam, "B", 22)
    pdf.cell(100, 10, fix(L["title"]))
    pdf.set_font(fam, "", 10)
    pdf.cell(0, 10, fix(L["original"]), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(255, 122, 31)
    pdf.set_line_width(0.6)
    pdf.line(18, pdf.get_y() + 1, 192, pdf.get_y() + 1)
    pdf.ln(4)
    pdf.set_font(fam, "", 10)
    for label, value in ((L["number"], inv["number"]), (L["date"], d(inv["issued"])), (L["tax_date"], d(inv["issued"]))):
        pdf.cell(55, 5.5, fix(label + ":"))
        pdf.set_font(fam, "B", 10)
        pdf.cell(0, 5.5, fix(value), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(fam, "", 10)
    pdf.ln(4)

    def party(x: float, title: str, p: dict) -> float:
        pdf.set_xy(x, y0)
        pdf.set_font(fam, "B", 10)
        pdf.cell(85, 6, fix(title.upper()), new_x="LEFT", new_y="NEXT")
        pdf.set_font(fam, "B", 11)
        pdf.multi_cell(85, 5.5, fix(p.get("name", "")), new_x="LEFT", new_y="NEXT")
        pdf.set_font(fam, "", 9.5)
        for key in ("address", "company_id", "vat_id", "person", "email", "phone"):
            if p.get(key):
                label = L.get(key, "")
                pdf.multi_cell(85, 5, fix((label + ": " if label and key != "address" else "") + p[key]
                                          if key != "address" else p[key]), new_x="LEFT", new_y="NEXT")
        return pdf.get_y()

    y0 = pdf.get_y()
    end1 = party(18, L["seller"], seller)
    end2 = party(107, L["buyer"], client)
    pdf.set_xy(18, max(end1, end2) + 6)

    pdf.set_font(fam, "B", 9.5)
    pdf.set_fill_color(240, 240, 240)
    pdf.set_draw_color(190, 190, 190)
    pdf.set_line_width(0.2)
    widths = (10, 88, 18, 28, 30)
    for w, h, al in zip(widths, (L["n"], L["desc"], L["qty"], L["price"], L["sum"]), "LLRRR"):
        pdf.cell(w, 7, fix(h), border=1, fill=True, align=al)
    pdf.ln(7)
    pdf.set_font(fam, "", 9.5)
    cur = inv["currency"]
    def header_row():
        pdf.set_font(fam, "B", 9.5)
        for w, h_, al in zip(widths, (L["n"], L["desc"], L["qty"], L["price"], L["sum"]), "LLRRR"):
            pdf.cell(w, 7, fix(h_), border=1, fill=True, align=al)
        pdf.ln(7)
        pdf.set_font(fam, "", 9.5)

    for n, it in enumerate(inv["items"], 1):
        line_sum = int((Decimal(it["qty"]) * it["price"]).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        rows = pdf.multi_cell(widths[1], 6, fix(it["desc"]), border=0, dry_run=True, output="LINES")
        h = max(6, 6 * len(rows))
        if pdf.get_y() + h > pdf.page_break_trigger:  # the whole row goes to the next page, with the header again
            pdf.add_page()
            pdf.set_xy(18, 18)
            header_row()
        y = pdf.get_y()
        pdf.set_x(18 + widths[0])
        pdf.multi_cell(widths[1], 6, fix(it["desc"]), border=0)
        pdf.set_xy(18, y)
        pdf.cell(widths[0], h, str(n), border=1)
        pdf.cell(widths[1], h, "", border=1)
        pdf.cell(widths[2], h, fix(it["qty"]), border=1, align="R")
        pdf.cell(widths[3], h, fix(money(it["price"], cur, bg)), border=1, align="R")
        pdf.cell(widths[4], h, fix(money(line_sum, cur, bg)), border=1, align="R")
        pdf.ln(h)
    net, vat, total = invoice_totals(inv)
    pdf.ln(3)
    for label, value, bold in ((L["net"], net, False), (f"{L['vat']} {inv['vat_rate']} %", vat, False), (L["total"], total, True)):
        pdf.set_x(18 + widths[0] + widths[1])
        pdf.set_font(fam, "B" if bold else "", 11 if bold else 9.5)
        pdf.cell(widths[2] + widths[3], 6.5, fix(label + ":"), align="R")
        pdf.cell(widths[4], 6.5, fix(money(value, cur, bg)), align="R", new_x="LMARGIN", new_y="NEXT")
    if cur == "EUR" and bg and inv["issued"] < "2026-08-09":  # the euro changeover's dual display (until 8 Aug 2026)
        pdf.set_x(18 + widths[0] + widths[1])
        pdf.set_font(fam, "", 8.5)
        bgn = int((Decimal(total) * BGN_PER_EUR).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        pdf.cell(widths[2] + widths[3] + widths[4], 5, fix(f"({money(bgn, 'BGN', True)} при курс 1,95583)"), align="R",
                 new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.set_font(fam, "", 9.5)
    if Decimal(inv["vat_rate"]) == 0:
        pdf.multi_cell(0, 5, fix(L["no_vat"]), new_x="LMARGIN", new_y="NEXT")
    pdf.multi_cell(0, 5, fix(f"{L['due']}: {d(inv['due'])}"), new_x="LMARGIN", new_y="NEXT")
    if seller.get("bank"):
        pdf.multi_cell(0, 5, fix(f"{L['bank']}: {seller['bank']}"), new_x="LMARGIN", new_y="NEXT")
    if inv.get("notes"):
        pdf.ln(2)
        pdf.multi_cell(0, 5, fix(inv["notes"]), new_x="LMARGIN", new_y="NEXT")
    if inv.get("status") == "void":
        pdf.ln(4)
        pdf.set_text_color(200, 40, 40)
        pdf.set_font(fam, "B", 14)
        pdf.multi_cell(0, 7, fix(f"{L['void']} - {L['void_note']}"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
    pdf.ln(10)
    pdf.set_font(fam, "", 9.5)
    pdf.cell(0, 5, fix(f"{L['made_by']}: {seller.get('person') or seller.get('name', '')}"), new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))


# ---------------------------------------------------------------- export (a spreadsheet for an accountant)

def export_rows(frm: date, to: date) -> tuple[list[list], list[list]]:
    data = load()
    bills = [["Vendor", "Category", "Amount", "Currency", "Due", "Status", "Paid on", "Number", "Notes"]]
    for b in sorted(data["bills"], key=lambda b: (b["due"] or b["added"])):
        when = date.fromisoformat(b["paid_on"] or b["due"] or b["added"])
        if frm <= when < to:
            bills.append([b["vendor"], b["category"], float(Decimal(b["amount"]) / 100), b["currency"], b["due"],
                          b["status"] + (" (estimate)" if b.get("estimate") else ""), b["paid_on"], b.get("number", ""),
                          b.get("notes", "")])
    invoices = [["Number", "Client", "Issued", "Due", "Net", "VAT", "Total", "Currency", "Status", "Paid on"]]
    for i in sorted(data["invoices"], key=lambda i: i["number"]):
        if frm <= date.fromisoformat(i["issued"]) < to:
            net, vat, total = invoice_totals(i)
            invoices.append([i["number"], i["client"]["name"], i["issued"], i["due"], float(Decimal(net) / 100),
                             float(Decimal(vat) / 100), float(Decimal(total) / 100), i["currency"], i["status"], i["paid_on"]])
    return bills, invoices


def _xl_clean(v):
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", v) if isinstance(v, str) else v


def write_xlsx(path: Path, bills: list[list], invoices: list[list], expenses: list[list] | None = None,
               deals: list[list] | None = None) -> None:
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill
    except ImportError:
        raise RuntimeError('Excel files need: pip install "vaelon[docs]"')
    wb = openpyxl.Workbook()
    sheets = [("Bills", bills), ("Invoices", invoices)] + ([("Budget", expenses)] if expenses and len(expenses) > 1 else []) \
        + ([("Deals", deals)] if deals and len(deals) > 1 else [])
    for n, (title, rows) in enumerate(sheets):
        ws = wb.active if n == 0 else wb.create_sheet()
        ws.title = title
        for row in rows:
            ws.append([_xl_clean(v) for v in row])  # a control character from a statement must not break the export
            for c in ws[ws.max_row]:
                if isinstance(c.value, str) and c.value[:1] in ("=", "+", "-", "@"):
                    c.data_type = "s"  # formula injection: a text from a statement or a client stays text
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="FF7A1F")
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(40, max(10, max(len(str(c.value or "")) for c in col) + 2))
        for row in ws.iter_rows(min_row=2):
            for c in row:
                if isinstance(c.value, float):
                    c.number_format = "#,##0.00"
    wb.save(str(path))


# ---------------------------------------------------------------- company mode: who may change what (and the journal)
from . import company as _co  # noqa: E402

add_bill = _co.guarded(add_bill, "bills.write", "bill added", lambda r, a, k: f"{r['vendor']} {money(r['amount'], r['currency'])}")
update_bill = _co.guarded(update_bill, "bills.write", "bill changed", lambda r, a, k: r["vendor"] if r else "")
delete_bill = _co.guarded(delete_bill, "bills.write", "bill deleted", lambda r, a, k: r["vendor"] if r else "")
mark_paid = _co.guarded(mark_paid, "bills.write", "bill marked paid",
                        lambda r, a, k: f"{r[0]['vendor']} {money(r[0]['amount'], r[0]['currency'])}" if r else "")
mark_unpaid = _co.guarded(mark_unpaid, "bills.write", "bill marked unpaid", lambda r, a, k: r["vendor"] if r else "")
set_profile = _co.guarded(set_profile, "profile.write", "business details changed", lambda r, a, k: ", ".join(sorted(k)))
new_invoice = _co.guarded(new_invoice, "invoices.write", "invoice issued",
                          lambda r, a, k: f"no. {r['number']} {r['client']['name']} {money(invoice_totals(r)[2], r['currency'])}")
update_invoice = _co.guarded(update_invoice, "invoices.write", "invoice changed",
                             lambda r, a, k: f"no. {r['number']}: " + ", ".join(f"{x}={v}" for x, v in k.items() if x != "file") if r else "")
restore_all = _co.guarded(restore_all, "bills.write", "undo", lambda r, a, k: "bills / invoices")
