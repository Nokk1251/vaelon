"""The budget: what comes in, what goes out, and a monthly limit per category.

    "похарчих 30 евро за храна"   "spent 12 EUR on coffee"   "получих заплата 2000 евро"
    "бюджет за храна 400 евро на месец"   "как съм с бюджета?"   "how much is left for eating out?"

Spending = the expenses you tell Vaelon + the bills you marked paid (bills.py) in that month, so a paid bill is never
typed twice. Each category can have a monthly limit, and there can be an overall one ("total"); when an expense
takes a category past 80 % or past its limit, the answer says so at once.
Everything is shown in ONE budget currency (EUR by default). Leva are converted at the fixed rate 1.95583; other
currencies cannot be converted without a live rate, so they are listed apart and not counted against a limit.
Vaelon never moves money: this is a record you keep. Stored ENCRYPTED in ~/.vaelon/budget.enc; amounts in cents.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from . import bills as B
from . import config
from .security import vault

FILE = "budget.enc"
_lock = threading.Lock()

# everyday spending categories, checked BEFORE the bill categories (bills.CATEGORIES); the first hit wins
EVERYDAY = {
    "groceries": r"храна|хранителни|продукти|хляб|мляко|плодове|зеленчуци|месо|магазин|супермаркет|пазар|лидл|lidl|билла|billa|кауфланд|kaufland|фантастико|"
                 r"groceries|grocery|supermarket|food shopping|food\b|metro cash|метро кеш",
    "eating out": r"ресторант|кафе|кафенце|обяд|вечеря|закуска|пица|бар\b|доставка на храна|restaurant|cafe|coffee|lunch|dinner|"
                  r"breakfast|pizza|takeaway|take-away|eating out|drinks",
    "transport": r"бензин|гориво|дизел|такси|градски транспорт|карта за градски|метро\b|автобус|билет за влак|паркинг|винетка|"
                 r"fuel|petrol|gasoline|diesel|taxi|uber\b|bolt\b|bus\b|metro\b(?!\s*cash)|train\b|parking|vignette|transport",
    "car": r"кола\b|колата\b|автомобил|сервиз|гуми\b|прегледа|car\b|garage|tyres|tires|mot\b",
    "shopping": r"дрехи|обувки|облекло|техника|clothes|shoes|clothing|electronics|shopping",
    "health": r"аптека|лекар|лекарства|зъболекар|преглед|болница|pharmacy|doctor|medicine|dentist|hospital|health",
    "entertainment": r"кино|театър|концерт|игра|игри|забавлени|cinema|movie|theatre|theater|concert|game|games|fun\b",
    "education": r"курс\b|курсове|учебни|книги|книга|училище|университет|такса за обучение|course\b|books?\b|school|tuition|education",
    "gifts": r"подарък|подаръци|gift|gifts|present\b",
    "travel": r"почивка|хотел|самолет|полет|екскурзия|пътуване|booking|airbnb|ryanair|wizz|holiday|vacation|hotel|flight|trip\b|travel",
    "home": r"мебели|ремонт|домакинск|за дома|furniture|repair|household|home\b",
    "kids": r"деца|детето|детски|детска градина|kids|children|child|nursery|daycare",
    "pets": r"куче|котка|ветеринар|храна за куче|dog|cat\b|vet\b|pet\b|pets",
    "personal care": r"фризьор|козметик|бръснар|hairdresser|barber|cosmetics|haircut",
}
CATEGORY_NAMES = tuple(EVERYDAY) + tuple(c for c in B.CATEGORY_NAMES if c != "other") + ("other",)
_BG = {"groceries": "храна", "eating out": "заведения", "transport": "транспорт", "car": "кола", "shopping": "покупки",
       "health": "здраве", "entertainment": "забавления", "education": "образование", "gifts": "подаръци",
       "travel": "пътувания", "home": "дом", "kids": "деца", "pets": "домашни любимци", "personal care": "лична грижа",
       "income": "приходи", "total": "общо"}
_BG_MONTHS = ["януари", "февруари", "март", "април", "май", "юни", "юли", "август", "септември", "октомври",
              "ноември", "декември"]


def category_of(text: str) -> str:
    low = (text or "").lower().strip()
    if low in CATEGORY_NAMES:
        return low
    for name, rx in EVERYDAY.items():
        if re.search(r"(?i)(?<![\w-])(?:" + rx + r")", low):
            return name
    return B.category_of(low)


def label(cat: str, bg: bool) -> str:
    if not bg:
        return cat
    return _BG.get(cat) or B.category_label(cat, True)


# ---------------------------------------------------------------- storage

def _path() -> Path:
    from . import company  # each company keeps its own money files (the personal workspace: ~/.vaelon as before)

    return company.data_dir() / FILE


def _empty() -> dict:
    return {"currency": "EUR", "limits": {}, "entries": [], "demo_limits": []}  # demo_limits: set by demo.py only


def load(strict: bool = False) -> dict:
    """`strict` (before every write): an unreadable file raises instead of being replaced by an empty one."""
    p = _path()
    if not p.exists():
        return _empty()
    try:
        data = json.loads(vault.decrypt_text(p.read_text("utf-8").strip()))
    except Exception:
        if strict:
            raise RuntimeError(f"{FILE} could not be read, so nothing was changed (the file is left as it is)")
        return _empty()
    base = _empty()
    if isinstance(data, dict):
        base.update({k: v for k, v in data.items() if k in base})
    return base


def _store(data: dict) -> None:
    _path().parent.mkdir(parents=True, exist_ok=True)
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(vault.encrypt_text(json.dumps(data, ensure_ascii=False)), "utf-8")
    vault.replace(tmp, _path())


def _change(fn):
    with _lock:
        data = load(strict=True)
        out = fn(data)
        _store(data)
        return out


def snapshot() -> dict:
    return json.loads(json.dumps(load(strict=True)))


def restore_all(data: dict) -> None:
    with _lock:
        _store(data)


# ---------------------------------------------------------------- money in the budget currency

def convert(c: int, cur: str, to: str) -> int | None:
    """Only exact conversions: the same currency, or EUR <-> BGN at the fixed rate."""
    if cur == to:
        return c
    if {cur, to} == {"EUR", "BGN"}:
        d = Decimal(c) / B.BGN_PER_EUR if cur == "BGN" else Decimal(c) * B.BGN_PER_EUR
        return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return None


def set_currency(cur: str) -> str:
    cur = str(cur).upper().strip()
    if cur not in B.CURRENCIES:
        raise ValueError("currency must be one of " + ", ".join(B.CURRENCIES))

    def go(data):
        old = data["currency"]
        if old != cur and data["limits"] and any(convert(v, old, cur) is None for v in data["limits"].values()):
            # 400 EUR would silently become 400 USD: no exact rate exists, so the user sets the limits again
            raise ValueError(f"the limits are in {old} and cannot be converted exactly - remove them first, then set "
                             f"them again in {cur}")
        data["limits"] = {k: convert(v, old, cur) for k, v in data["limits"].items()}
        data["currency"] = cur
        return cur

    return _change(go)


# ---------------------------------------------------------------- entries

def add(kind: str, amount: int, currency: str = "", category: str = "", note: str = "", on: date | None = None) -> dict:
    """An expense or an income. `category` is guessed from the note when empty."""
    if kind not in ("expense", "income"):
        raise ValueError("kind must be expense or income")
    if amount <= 0:
        raise ValueError("the amount must be above zero")
    amount, cur = B.euro_first(int(amount), (currency or load()["currency"]).upper())
    if cur not in B.CURRENCIES:
        raise ValueError("currency must be one of " + ", ".join(B.CURRENCIES))
    note = re.sub(r"\s+", " ", str(note)).strip()[:200]
    if kind == "income":
        cat = "income"
    else:
        cat = category if category in CATEGORY_NAMES else category_of(f"{category} {note}")
    e = {"id": uuid.uuid4().hex[:6], "kind": kind, "amount": int(amount), "currency": cur, "category": cat,
         "note": note, "date": (on or date.today()).isoformat()}

    def go(data):
        data["entries"].append(e)
        return e

    return _change(go)


def remove(eid: str) -> dict | None:
    def go(data):
        gone = next((e for e in data["entries"] if e["id"] == eid), None)
        if gone:
            data["entries"].remove(gone)
        return gone

    return _change(go)


def set_limit(category: str, amount: int | None) -> dict:
    """A monthly limit for a category ('total' = everything). None removes it."""
    cat = "total" if str(category).lower().strip() in ("total", "all", "everything", "общо", "всичко", "") else category_of(category)

    def go(data):
        if amount is None:
            data["limits"].pop(cat, None)
        else:
            if amount <= 0:
                raise ValueError("the limit must be above zero")
            data["limits"][cat] = int(amount)
        return dict(data["limits"])

    _change(go)
    return {"category": cat, "amount": amount}


# ---------------------------------------------------------------- a month

def month_of(text: str = "", today: date | None = None) -> date:
    """'this month' / 'last month' / 'ноември' / '2026-10' -> the first day of that month. Default: this month."""
    today = today or date.today()
    low = (text or "").lower()
    m = re.search(r"(20\d\d)-(\d{1,2})(?!\d)", low)
    if m:
        return date(int(m.group(1)), int(m.group(2)), 1)
    if re.search(r"last month|previous month|миналия месец|предния месец", low):
        return (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    m = re.search(r"(?i)(?<![\w])(" + B._MON_ALT + r")(?![\w])", low)
    if m:
        mo = B._MONTHS[m.group(1)]
        return date(today.year if mo <= today.month else today.year - 1, mo, 1)
    return today.replace(day=1)


def month_label(first: date, bg: bool) -> str:
    return f"{_BG_MONTHS[first.month - 1]} {first.year}" if bg else first.strftime("%B %Y")


def month(first: date) -> dict:
    """Everything about one month, in the budget currency:
    {income, spent, left, by_category {cat: cents}, limits, apart {cur: cents}, entries, bills}."""
    data = load()
    cur = data["currency"]
    end = B._shift(first, "monthly")
    rows = [e for e in data["entries"] if first <= date.fromisoformat(e["date"]) < end]
    paid = [b for b in B.load()["bills"] if b["status"] == "paid" and b.get("paid_on")
            and first <= date.fromisoformat(b["paid_on"]) < end]
    income = spent = 0
    by_cat: dict[str, int] = {}
    apart: dict[str, int] = {}
    for kind, cat, c, ccy in ([(e["kind"], e["category"], e["amount"], e["currency"]) for e in rows]
                              + [("expense", b["category"], b["amount"], b["currency"]) for b in paid]):
        v = convert(c, ccy, cur)
        if v is None:
            apart[ccy] = apart.get(ccy, 0) + (c if kind == "expense" else 0)
            continue
        if kind == "income":
            income += v
        else:
            spent += v
            by_cat[cat] = by_cat.get(cat, 0) + v
    return {"first": first, "currency": cur, "income": income, "spent": spent, "left": income - spent,
            "by_category": by_cat, "limits": dict(data["limits"]), "apart": apart,
            "entries": sorted(rows, key=lambda e: (e["date"], e["id"]), reverse=True), "bills": paid}


def pct(part: int, whole: int) -> int:
    if not whole:
        return 0
    return int((Decimal(100 * part) / Decimal(whole)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))  # 90.5 -> 91


def report(first: date, bg: bool, category: str = "") -> str:
    m = month(first)
    cur, money = m["currency"], (lambda c: B.money(c, m["currency"], bg))
    name = month_label(first, bg)
    if category:
        spent, limit = m["by_category"].get(category, 0), m["limits"].get(category)
        lab = label(category, bg)
        if limit:
            left = limit - spent
            if bg:
                return (f"За {lab} през {name}: похарчени {money(spent)} от {money(limit)} ({pct(spent, limit)} %); "
                        + (f"остават {money(left)}." if left >= 0 else f"над лимита с {money(-left)}."))
            return (f"{lab.capitalize()} in {name}: {money(spent)} of {money(limit)} spent ({pct(spent, limit)} %); "
                    + (f"{money(left)} left." if left >= 0 else f"{money(-left)} over the limit."))
        return (f"За {lab} през {name} са похарчени {money(spent)} (няма лимит)." if bg
                else f"{lab.capitalize()} in {name}: {money(spent)} spent (no limit set).")
    if not m["income"] and not m["spent"] and not m["apart"]:
        return (f"За {name} нямам записани приходи и разходи. Кажи например „похарчих 30 евро за храна“."
                if bg else f"Nothing recorded for {name} yet. Say e.g. \"spent 30 EUR on groceries\".")
    lines = [(f"{name.capitalize()}: приходи {money(m['income'])}, разходи {money(m['spent'])}, "
              + (f"остават {money(m['left'])}." if m["left"] >= 0 else f"на минус {money(-m['left'])}.")) if bg
             else (f"{name}: income {money(m['income'])}, spent {money(m['spent'])}, "
                   + (f"{money(m['left'])} left." if m["left"] >= 0 else f"{money(-m['left'])} short."))]
    cats = sorted(set(m["by_category"]) | {c for c in m["limits"] if c != "total"}, key=lambda c: -m["by_category"].get(c, 0))
    over = []
    for c in cats:
        s, lim = m["by_category"].get(c, 0), m["limits"].get(c)
        if lim:
            lines.append(f"• {label(c, bg)}: {money(s)} / {money(lim)} ({pct(s, lim)} %)")
            if s > lim:
                over.append(label(c, bg))
        else:
            lines.append(f"• {label(c, bg)}: {money(s)}")
    tot = m["limits"].get("total")
    if tot:
        lines.append((f"Общ лимит: {money(m['spent'])} / {money(tot)} ({pct(m['spent'], tot)} %)" if bg
                      else f"Overall limit: {money(m['spent'])} / {money(tot)} ({pct(m['spent'], tot)} %)"))
        if m["spent"] > tot:
            over.append(label("total", bg))
    if over:
        lines.append(("Над лимита: " if bg else "Over the limit: ") + ", ".join(over) + ".")
    if m["apart"]:
        lines.append((f"Не са включени (друга валута): " if bg else "Not counted (other currency): ")
                     + B.totals_text(m["apart"], bg))
    if cur and m["bills"]:
        lines.append(("(платените сметки са включени)" if bg else "(paid bills are included)"))
    return "\n".join(lines)


def warning(category: str, bg: bool, before: int | None = None, on=None) -> str:
    """After an expense: say when the category (or the whole month) crossed 80 % or its limit - in the month of the
    expense itself (a back-dated one counts in its own month)."""
    day = date.fromisoformat(on[:10]) if isinstance(on, str) and on else on if isinstance(on, date) else date.today()
    m = month(day.replace(day=1))
    out = []
    for cat, spent in ((category, m["by_category"].get(category, 0)), ("total", m["spent"])):
        lim = m["limits"].get(cat)
        if not lim:
            continue
        lab = label(cat, bg)
        money = B.money(spent, m["currency"], bg)
        if spent > lim:
            out.append(f" Внимание: {lab} е над лимита ({money} от {B.money(lim, m['currency'], bg)})." if bg
                       else f" Careful: {lab} is over its limit ({money} of {B.money(lim, m['currency'])}).")
        elif spent >= lim * 0.8:
            out.append(f" {lab.capitalize()}: {pct(spent, lim)} % от лимита са похарчени." if bg
                       else f" {lab.capitalize()}: {pct(spent, lim)} % of the limit is used.")
    return "".join(out)


def entry_line(e: dict, bg: bool) -> str:
    sign = "+" if e["kind"] == "income" else "-"
    d = date.fromisoformat(e["date"])
    return f"{d:%d.%m} {sign}{B.money(e['amount'], e['currency'], bg)} {label(e['category'], bg)}" + (f" ({e['note']})" if e["note"] else "")


def export_rows(frm: date, to: date) -> list[list]:
    rows = [["Date", "Kind", "Category", "Amount", "Currency", "Note"]]
    for e in sorted(load()["entries"], key=lambda e: e["date"]):
        if frm <= date.fromisoformat(e["date"]) < to:
            rows.append([e["date"], e["kind"], e["category"], float(Decimal(e["amount"]) / 100), e["currency"], e["note"]])
    return rows


# ---------------------------------------------------------------- company mode: who may change what (and the journal)
from . import company as _co  # noqa: E402

add = _co.guarded(add, "budget.write", "budget entry added",
                  lambda r, a, k: f"{r['kind']} {B.money(r['amount'], r['currency'])} {r['category']} {r['note']}".strip())
remove = _co.guarded(remove, "budget.write", "budget entry removed",
                     lambda r, a, k: f"{r['kind']} {B.money(r['amount'], r['currency'])} {r['note']}" if r else "")
set_limit = _co.guarded(set_limit, "budget.limits", "limit set", lambda r, a, k: f"{r['category']}: {r['amount']}")
set_currency = _co.guarded(set_currency, "budget.limits", "budget currency", lambda r, a, k: r)
restore_all = _co.guarded(restore_all, "budget.write", "undo", lambda r, a, k: "budget")
