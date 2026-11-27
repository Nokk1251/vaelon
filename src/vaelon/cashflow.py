"""Cash flow (issue #42): what comes in and goes out over the next 30 / 60 / 90 days, week by week, and a warning when
the money may run short. It only READS what Vaelon already has - nothing new is connected, nothing is paid.

- Money in: unpaid invoices by due date (late ones counted today and flagged), plus the user's usual income from
  the budget (the average of the last three months that have entries, marked as an estimate).
- Money out: unpaid bills by due date, the next bills of repeating ones (estimates), plus usual everyday spending from
  the budget (same average, an estimate).
- Deals that may close in the period are shown APART (weighted by their chance) and never counted as money.
- A starting balance the user types in (kept in the budget, per company); without it the forecast shows the change.
- The lowest point and the warning are worked out DAY by day (a bill on Tuesday is not hidden by money that comes in
  on Friday); the table shows weeks.
- One currency (the budget's); exact conversions only (EUR <-> BGN); other currencies are listed apart.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from . import bills as B
from . import budget as BU
from . import deals as D

SERIES_GAP = 25  # days: another unpaid bill of the same vendor this close to a predicted date IS that payment
EARLY = 7  # days: a bill of a series may come this much earlier than expected and still be its next payment


def _months_back(first: date, n: int) -> list[date]:
    out, d = [], first
    for _ in range(n):
        d = (d - timedelta(days=1)).replace(day=1)
        out.append(d)
    return out


def _usual(today: date, cur: str) -> tuple[int, int]:
    """(monthly income, monthly everyday spending) from the budget entries of the last three full months, averaged
    over the months that HAVE entries (a new user with one month is not divided by three). Bills are not included:
    they are counted one by one."""
    data = BU.load()
    oldest = _months_back(today.replace(day=1), 3)[-1]
    income = spent = 0
    months = set()
    for e in data["entries"]:
        d = date.fromisoformat(e["date"])
        if not oldest <= d < today.replace(day=1):
            continue
        v = BU.convert(e["amount"], e["currency"], cur)
        if v is None:
            continue
        months.add((d.year, d.month))
        if e["kind"] == "income":
            income += v
        else:
            spent += v
    if not months:
        return 0, 0
    return round(income / len(months)), round(spent / len(months))


def _week_of(d: date, today: date) -> str:
    return (today + timedelta(days=7 * ((d - today).days // 7))).isoformat()


def forecast(days: int = 90, today: date | None = None) -> dict:
    """{"currency", "days", "balance", "balance_on", "weeks": [{"from","to","in","out","net","balance"}], "items": [...],
    "late_in", "late_out", "undated_out", "possible", "apart", "lowest", "short_week", "in_total", "out_total"}."""
    from . import company

    company.require("bills.read")
    company.require("invoices.read")
    company.require("budget.read")
    today = today or date.today()
    days = max(7, min(366, int(days)))
    end = today + timedelta(days=days - 1)  # today is the first of DAYS days
    budget = BU.load()
    cur = budget["currency"]
    bal = budget.get("balance") or None
    items, apart, undated = [], {}, 0

    def put(when: date, kind: str, label: str, cents: int, ccy: str, late=False, estimate=False, source=""):
        v = BU.convert(int(cents), ccy, cur)
        if v is None:
            apart[ccy] = apart.get(ccy, 0) + (cents if kind == "in" else -cents)
            return
        items.append({"date": max(when, today).isoformat(), "kind": kind, "label": label, "amount": v, "late": late,
                      "estimate": estimate, "source": source})

    data = B.load()
    for inv in data["invoices"]:
        if inv.get("status") != "unpaid":
            continue
        due = date.fromisoformat(inv["due"]) if inv.get("due") else today
        if due <= end:
            put(due, "in", f"invoice {inv['number']} - {inv['client']['name']}", B.invoice_totals(inv)[2],
                inv["currency"], late=due < today, source="invoice")
    open_bills = [b for b in data["bills"] if b.get("status") == "unpaid"]
    # Series of repeating bills (same vendor, category and repeat). A bill joins a series when it is that series' next
    # payment - at most EARLY days before the date the series expects next or SERIES_GAP days after it (the real
    # December bill on the 12th after November's on the 5th) - or the same bill typed twice; otherwise it starts a
    # series of its own (two payments of one vendor in a month, on the 1st and the 17th). Only the last bill of each
    # series predicts the payments after it.
    chains: list[list[dict]] = []
    for b in sorted((x for x in open_bills if x.get("due") and x.get("repeat")), key=lambda x: x["due"]):
        due = date.fromisoformat(b["due"])
        best, gap = None, None
        for ch in chains:
            last = ch[-1]
            if (last["vendor"].lower(), last.get("category", ""), last["repeat"]) != (
                    b["vendor"].lower(), b.get("category", ""), b["repeat"]):
                continue
            ldue = date.fromisoformat(last["due"])
            if ldue == due:  # the same bill twice: it does not predict a second time
                best, gap = ch, -1
                break
            off = (due - B._shift(ldue, last["repeat"], int(last.get("day") or ldue.day))).days
            if -EARLY <= off <= SERIES_GAP and (gap is None or abs(off) < gap):
                best, gap = ch, abs(off)
        if best is None:
            chains.append([b])
        elif gap != -1:
            best.append(b)
    # one-off bills of a vendor (a real next bill typed in by hand): each stands for ONE predicted payment of the same
    # vendor and category - the nearest one, matched over all series at once (closest pairs first)
    one_offs = [(b["vendor"].lower(), b.get("category", ""), date.fromisoformat(b["due"]))
                for b in open_bills if b.get("due") and not b.get("repeat")]
    projected = []  # (date, bill of the series)
    for ch in chains:
        b = ch[-1]
        due = date.fromisoformat(b["due"])
        day = int(b.get("day") or due.day)
        nxt = B._shift(due, b["repeat"], day)
        while nxt <= end:
            projected.append((nxt, b))
            nxt = B._shift(nxt, b["repeat"], day)
    pairs = sorted((abs((o[2] - p[0]).days), i, j) for i, p in enumerate(projected) for j, o in enumerate(one_offs)
                   if (o[0], o[1]) == (p[1]["vendor"].lower(), p[1].get("category", ""))
                   and -EARLY <= (o[2] - p[0]).days <= SERIES_GAP)  # a correction mid-month is not next month's bill
    taken_p, taken_o = set(), set()
    for _, i, j in pairs:
        if i not in taken_p and j not in taken_o:
            taken_p.add(i)
            taken_o.add(j)

    for b in open_bills:
        if not b.get("due"):
            v = BU.convert(b["amount"], b["currency"], cur)
            if v is None:
                apart[b["currency"]] = apart.get(b["currency"], 0) - b["amount"]
            else:
                undated += v
            continue
        due = date.fromisoformat(b["due"])
        if due <= end:
            put(due, "out", b["vendor"], b["amount"], b["currency"], late=due < today, estimate=bool(b.get("estimate")),
                source="bill")
    for i, (nxt, b) in enumerate(projected):
        if i not in taken_p:  # a taken one is already a real bill
            put(nxt, "out", b["vendor"], b["amount"], b["currency"], late=nxt < today, estimate=True, source="repeat")
    inc, spend = _usual(today, cur)
    weeks = math.ceil(days / 7)
    for w in range(weeks):
        start = today + timedelta(days=7 * w)
        share = min(7, (end - start).days + 1) / 30.44
        if inc:
            put(start, "in", "usual income (average of recent months)", round(inc * share), cur, estimate=True,
                source="usual")
        if spend:
            put(start, "out", "usual everyday spending (average of recent months)", round(spend * share), cur,
                estimate=True, source="usual")

    possible = []
    if company.can("deals.read"):
        for d in D.load():
            if d.get("stage") in ("won", "lost") or not d.get("close") or not d.get("value"):
                continue
            close = date.fromisoformat(d["close"])
            if today <= close <= end:
                v = BU.convert(D.weighted(d), d["currency"], cur)
                if v is not None:
                    possible.append({"client": d["client"], "title": d.get("title", ""), "close": d["close"],
                                     "weighted": v, "stage": d["stage"]})

    start_balance = int(bal["cents"]) if bal else 0
    rows, running = [], start_balance
    for w in range(weeks):
        frm = today + timedelta(days=7 * w)
        to = min(frm + timedelta(days=6), end)
        inside = [x for x in items if frm.isoformat() <= x["date"] <= to.isoformat()]
        i = sum(x["amount"] for x in inside if x["kind"] == "in")
        o = sum(x["amount"] for x in inside if x["kind"] == "out")
        running += i - o
        rows.append({"from": frm.isoformat(), "to": to.isoformat(), "in": i, "out": o, "net": i - o, "balance": running})
    # the lowest point day by day: money out on Tuesday is not hidden by money in on Friday of the same week
    lowest, short_week, run = (start_balance, today.isoformat()), "", start_balance
    if bal and start_balance < 0:
        short_week = today.isoformat()
    by_day: dict[str, int] = {}
    for x in items:
        by_day[x["date"]] = by_day.get(x["date"], 0) + (x["amount"] if x["kind"] == "in" else -x["amount"])
    for day in sorted(by_day):
        run += by_day[day]
        week = _week_of(date.fromisoformat(day), today)
        if run < lowest[0]:
            lowest = (run, week)
        if bal and run < 0 and not short_week:
            short_week = week
    return {"currency": cur, "days": days, "today": today.isoformat(),
            "balance": start_balance if bal else None, "balance_on": bal.get("on", "") if bal else "",
            "weeks": rows, "items": sorted(items, key=lambda x: (x["date"], x["kind"])),
            "in_total": sum(r["in"] for r in rows), "out_total": sum(r["out"] for r in rows),
            "late_in": sum(x["amount"] for x in items if x["late"] and x["kind"] == "in"),
            "late_out": sum(x["amount"] for x in items if x["late"] and x["kind"] == "out"),
            "undated_out": undated, "possible": sorted(possible, key=lambda x: x["close"]), "apart": apart,
            "lowest": {"balance": lowest[0], "week": lowest[1]} if bal else None, "short_week": short_week}


def signed_cents(text: str) -> int:
    """'-150,50' -> -15050; '2 000' -> 200000 (a balance can be below zero)."""
    s = str(text).strip()
    neg = s.startswith("-") or s.startswith("−")
    return -B.cents(s.lstrip("-− ")) if neg else B.cents(s)


def afford(amount: int, days: int = 30, today: date | None = None) -> dict:
    """Can AMOUNT (budget currency, cents) be spent now without the balance going below zero on any day of the next
    DAYS?"""
    f = forecast(days, today)
    if f["balance"] is None:
        return {"known": False, "forecast": f}
    low = f["lowest"]["balance"]
    return {"known": True, "ok": low - amount >= 0, "lowest_after": low - amount, "forecast": f}


def text(f: dict, bg: bool = False) -> str:
    """A short answer in words (English; only English phrases reach it without the model - the model answers others
    in the user's language)."""
    cur = f["currency"]
    m = lambda c: B.money(c, cur, False)  # noqa: E731
    lines = [f"Cash flow for the next {f['days']} days ({cur}): in {m(f['in_total'])}, out {m(f['out_total'])}."]
    if f["balance"] is None:
        lines.append(f"Change over the period: {m(f['in_total'] - f['out_total'])}. Tell me your current balance "
                     "(\"my balance is 2000 EUR\") for a real forecast.")
    else:
        age = (date.fromisoformat(f["today"]) - date.fromisoformat(f["balance_on"])).days if f["balance_on"] else 0
        old = f" - {age} days old, update it for a true picture" if age > 7 else ""
        lines.append(f"Balance now {m(f['balance'])} (as of {f['balance_on']}{old}), at the end "
                     f"{m(f['weeks'][-1]['balance'] if f['weeks'] else f['balance'])}; lowest {m(f['lowest']['balance'])} "
                     f"in the week of {f['lowest']['week']}.")
        if f["short_week"]:
            lines.append(f"WARNING: money may run short in the week of {f['short_week']}.")
    if f["late_in"]:
        lines.append(f"Late invoices (clients owe you): {m(f['late_in'])}.")
    if f["late_out"]:
        lines.append(f"Late bills (you owe): {m(f['late_out'])}.")
    if f["undated_out"]:
        lines.append(f"Bills without a due date, not placed in a week: {m(f['undated_out'])}.")
    if f["possible"]:
        tot = sum(p["weighted"] for p in f["possible"])
        lines.append(f"Possible from open deals (weighted by their chance, NOT counted): {m(tot)}.")
    if f["apart"]:
        lines.append("Not converted (other currencies): " + ", ".join(B.money(abs(v), k, False) + (" out" if v < 0 else " in")
                                                                       for k, v in f["apart"].items()) + ".")
    if any(x["estimate"] for x in f["items"]):
        lines.append("Estimates included: repeating bills and the usual income / spending of recent months.")
    return "\n".join(lines)
