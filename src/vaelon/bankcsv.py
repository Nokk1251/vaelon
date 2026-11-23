"""Bank statements (CSV) into the budget - read on this computer, never sent anywhere, no bank login ever.

Download the statement as CSV from your online banking (or Revolut / Wise), attach it and say "внеси извлечението",
or use Money > Budget > Import bank CSV. Vaelon then:
  * reads the columns by their names (date, amount or debit/credit, description, currency) in Bulgarian or English,
    with ; or , or tab, UTF-8 or Windows-1251, decimal comma or point, dd.mm.yyyy or yyyy-mm-dd;
  * turns a payment that matches an unpaid BILL (same amount, near its due date) into "bill paid" - not a second
    expense; an incoming payment that matches an unpaid INVOICE (its total, the client or the number in the text)
    marks the invoice paid;
  * adds everything else as budget expenses / income, the category guessed from the description;
  * never imports the same transaction twice (a fingerprint of date + amount + text), and leva become euro.
The statement is untrusted text: it is only searched for these fields, nothing in it is followed.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import date, datetime
from pathlib import Path

from . import bills as B
from . import budget as BU

MAX_BYTES = 5_000_000
HEAD = {
    "date": r"^(?:completed date|booking date|transaction date|date|дата(?: на (?:операция|осчетоводяване|транзакция))?|"
            r"вальор|value date|started date|posting date)$",
    "amount": r"^(?:amount|сума|стойност|amount \(\w+\)|сума \(\w+\)|transaction amount)$",
    "debit": r"^(?:debit|дебит|теглене|paid out|out|money out|разход|withdrawal)$",
    "credit": r"^(?:credit|кредит|постъпление|paid in|in|money in|приход|deposit)$",
    "sign": r"^(?:d/c|dr/cr|дт/кт|д/к|тип|type of entry|debit/credit|дебит/кредит)$",
    "desc": r"^(?:description|описание|основание|детайли|details|reference|payee|получател|наредител|контрагент|"
            r"merchant|name|partner|beneficiary|counterparty|информация|текст|narrative|memo)$",
    "currency": r"^(?:currency|валута|ccy)$",
    "state": r"^(?:state|status|статус|състояние)$",
}
DATE_FORMATS = ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%y", "%m/%d/%Y")
SKIP_STATES = re.compile(r"(?i)revert|declin|fail|cancel|pending|отказ|анул")


def _text(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _date(s: str) -> date | None:
    s = s.strip()
    first = s.split()[0] if s.split() else s  # "1.11.2026 10:00" -> "1.11.2026" (a time after the date is dropped)
    for cut in (first, s[:10], s[:8]):
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(cut, fmt).date()
            except ValueError:
                continue
    return None


def _amount(s: str) -> int | None:
    s = (s or "").strip().replace(" ", " ").replace("−", "-").replace("–", "-")  # Unicode minus signs
    if not s or not re.search(r"\d", s):
        return None
    neg = s.startswith("-") or s.endswith("-") or (s.startswith("(") and s.endswith(")"))
    try:
        c = B.cents(re.sub(r"[^\d.,]", "", s))
    except ValueError:
        return None
    return -c if neg else c


def parse(raw: bytes) -> list[dict]:
    """The transactions of a statement: [{date, amount (cents, minus = money out), currency, text}]."""
    if len(raw) > MAX_BYTES:
        raise ValueError("the file is too large for a statement (5 MB at most)")
    text = _text(raw)
    lines = text.splitlines()
    sample = "\n".join(lines[:40])
    try:
        delim = csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
    except csv.Error:
        delim = ";" if sample.count(";") > sample.count(",") else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    # the header: the first row (of the first 25) where a date column AND an amount (or debit/credit) column are named
    cols, start = None, 0
    for n, row in enumerate(rows[:25]):
        found = {}
        for k, cell in enumerate(row):
            name = re.sub(r"\s+", " ", cell.strip().lower().strip("\"'"))
            for key, rx in HEAD.items():
                if key not in found and re.match(rx, name):
                    found[key] = k
                    break
        if "date" in found and ("amount" in found or "debit" in found or "credit" in found):
            cols, start = found, n + 1
            break
    if not cols:
        raise ValueError("I could not find the columns (a date and an amount or debit/credit) - is this a bank statement CSV?")
    out = []
    unread = 0
    for row in rows[start:]:
        if not any(c.strip() for c in row):
            continue
        if len(row) <= max(cols.values()):
            unread += 1
            continue
        d = _date(row[cols["date"]])
        if not d:
            unread += 1  # counted and shown, never dropped silently
            continue
        if "state" in cols and SKIP_STATES.search(row[cols["state"]]):
            continue
        if "amount" in cols:
            amount = _amount(row[cols["amount"]])
            if amount is not None and "sign" in cols and re.match(r"(?i)^\s*(d|dr|д|дт|debit|дебит)\b", row[cols["sign"]]):
                amount = -abs(amount)
        else:
            out_ = _amount(row[cols["debit"]]) if "debit" in cols else None
            in_ = _amount(row[cols["credit"]]) if "credit" in cols else None
            amount = (abs(in_) if in_ else 0) - (abs(out_) if out_ else 0) if (out_ or in_) else None
        if not amount:
            continue
        cur = (row[cols["currency"]].strip().upper() if "currency" in cols else "") or "EUR"
        cur = {"ЛВ": "BGN", "ЛВ.": "BGN", "ЕВРО": "EUR", "EURO": "EUR", "€": "EUR", "$": "USD", "£": "GBP"}.get(cur, cur)
        c, cur = B.euro_first(abs(amount), cur)
        text_ = re.sub(r"\s+", " ", row[cols["desc"]] if "desc" in cols else "").strip()[:200]
        out.append({"date": d, "amount": c if amount > 0 else -c, "currency": cur, "text": text_})
    if not out:
        raise ValueError("no transactions found in the file")
    if unread:
        out[0]["unread"] = unread  # carried to the summary
    return out


def fingerprint(t: dict) -> str:
    return hashlib.sha256(f"{t['date']}|{t['amount']}|{t['currency']}|{t['text'].lower()}".encode()).hexdigest()[:16]


def _words(s: str) -> list[str]:
    return [w for w in re.findall(r"[\wа-яё]{4,}", s.lower()) if w not in {"ltd.", "ood", "eood", "оод", "еоод", "ltd"}]


def _bill_for(t: dict, bills: list[dict]) -> dict | None:
    """An unpaid bill this payment pays: the same amount, within 30 days of its due date, AND the text names it -
    its vendor, its number or its category. An amount alone is not enough ("Restaurant -25.00" is not the 25 EUR phone
    bill - found by the code review 2026-11-15)."""
    low = t["text"].lower()
    for b in bills:
        if b["status"] != "unpaid" or b["currency"] != t["currency"] or b["amount"] != -t["amount"]:
            continue
        if b["due"] and abs((date.fromisoformat(b["due"]) - t["date"]).days) > 30:
            continue
        named = (any(w in low for w in _words(b["vendor"])) or (b.get("number") and b["number"].lower() in low)
                 or (b["category"] != "other" and B.category_of(low) == b["category"]))
        if named:
            return b
    return None


def _invoice_for(t: dict, invoices: list[dict]) -> dict | None:
    """An unpaid invoice this money pays: its total, AND its number as a whole number or the client's name in the text."""
    low = t["text"].lower()
    if not low:
        return None
    for i in invoices:
        if i["status"] != "unpaid" or i["currency"] != t["currency"] or B.invoice_totals(i)[2] != t["amount"]:
            continue
        num = i["number"].lstrip("0") if i["number"].isdigit() else i["number"].lower()
        by_number = bool(num) and re.search(r"(?<![\w])0*" + re.escape(num) + r"(?![\w])", low)
        by_client = any(w in low for w in _words(i["client"].get("name", "")))
        if by_number or by_client:
            return i
    return None


def run(raw: bytes, apply: bool = False) -> dict:
    """Read a statement; with apply=True also record it. Returns the summary (and what was matched)."""
    tx = parse(raw)
    data = B.load()
    seen = {e.get("ref") for e in BU.load()["entries"] if e.get("ref")} | {b.get("ref") for b in data["bills"] if b.get("ref")} \
        | {i.get("ref") for i in data["invoices"] if i.get("ref")}
    summary = {"found": len(tx), "from": min(t["date"] for t in tx).isoformat(), "to": max(t["date"] for t in tx).isoformat(),
               "expenses": 0, "spent": {}, "income": 0, "received": {}, "bills": [], "invoices": [], "skipped": 0, "added": 0,
               "other": {}, "unread": tx[0].get("unread", 0)}
    bills = [dict(b) for b in data["bills"]]
    invoices = [dict(i) for i in data["invoices"]]
    count: dict[str, int] = {}
    for t in tx:
        fp = fingerprint(t)
        count[fp] = count.get(fp, 0) + 1
        ref = f"{fp}#{count[fp]}"  # two equal coffees on one day are two lines; the same file again matches the same refs
        if ref in seen:
            summary["skipped"] += 1
            continue
        seen.add(ref)
        if t["currency"] not in B.CURRENCIES:  # e.g. HUF from a trip: shown, never half-imported
            summary["other"][t["currency"]] = summary["other"].get(t["currency"], 0) + abs(t["amount"])
            continue
        t["text"] = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", t.get("text") or "").strip()
        if t["amount"] < 0:
            b = _bill_for(t, bills)
            if b:
                b["status"] = "paid"  # so the same bill is not matched twice in this file
                summary["bills"].append({"id": b["id"], "vendor": b["vendor"], "amount": b["amount"], "currency": b["currency"],
                                         "date": t["date"].isoformat()})
                if apply:
                    B.mark_paid(b["id"], t["date"])
                    B.update_bill(b["id"], ref=ref)
                continue
            summary["expenses"] += 1
            summary["spent"][t["currency"]] = summary["spent"].get(t["currency"], 0) - t["amount"]
            if apply:
                e = BU.add("expense", -t["amount"], t["currency"], "", t["text"] or "bank", t["date"])
                _tag(e["id"], ref)
                summary["added"] += 1
        else:
            i = _invoice_for(t, invoices)
            if i:
                i["status"] = "paid"
                summary["invoices"].append({"id": i["id"], "number": i["number"], "client": i["client"]["name"],
                                            "date": t["date"].isoformat()})
                if apply:
                    B.update_invoice(i["id"], status="paid", paid_on=t["date"].isoformat(), ref=ref)
                continue
            summary["income"] += 1
            summary["received"][t["currency"]] = summary["received"].get(t["currency"], 0) + t["amount"]
            if apply:
                e = BU.add("income", t["amount"], t["currency"], "", t["text"] or "bank", t["date"])
                _tag(e["id"], ref)
                summary["added"] += 1
    return summary


def _tag(eid: str, ref: str) -> None:
    def go(data):
        for e in data["entries"]:
            if e["id"] == eid:
                e["ref"], e["source"] = ref, "bank"
    BU._change(go)


def summary_text(s: dict, bg: bool, applied: bool) -> str:
    money = (lambda t: B.totals_text(t, bg))
    if bg:
        lines = [f"Извлечение {s['from']} - {s['to']}: {s['found']} движения."]
        lines.append(f"• разходи: {s['expenses']} ({money(s['spent'])})")
        lines.append(f"• приходи: {s['income']} ({money(s['received'])})")
        if s["bills"]:
            lines.append("• платени сметки: " + ", ".join(f"{b['vendor']} {B.money(b['amount'], b['currency'], True)}" for b in s["bills"]))
        if s["invoices"]:
            lines.append("• платени фактури: " + ", ".join(f"№ {i['number']} {i['client']}" for i in s["invoices"]))
        if s["skipped"]:
            lines.append(f"• вече внесени (пропуснах ги): {s['skipped']}")
        if s.get("other"):
            lines.append("• в друга валута (не ги внасям): " + money(s["other"]))
        if s.get("unread"):
            lines.append(f"• редове, които не успях да прочета: {s['unread']}")
        lines.append("Внесох ги в бюджета. „Undo“ ги маха наведнъж." if applied else "Да ги внеса ли?")
    else:
        lines = [f"Statement {s['from']} - {s['to']}: {s['found']} transactions."]
        lines.append(f"• money out: {s['expenses']} ({money(s['spent'])})")
        lines.append(f"• money in: {s['income']} ({money(s['received'])})")
        if s["bills"]:
            lines.append("• bills paid: " + ", ".join(f"{b['vendor']} {B.money(b['amount'], b['currency'])}" for b in s["bills"]))
        if s["invoices"]:
            lines.append("• invoices paid: " + ", ".join(f"no. {i['number']} {i['client']}" for i in s["invoices"]))
        if s["skipped"]:
            lines.append(f"• already imported (skipped): {s['skipped']}")
        if s.get("other"):
            lines.append("• in another currency (not imported): " + money(s["other"]))
        if s.get("unread"):
            lines.append(f"• lines I could not read: {s['unread']}")
        lines.append("Recorded in your budget. Undo takes it all back at once." if applied else "Import them?")
    return "\n".join(lines)


def import_file(path: Path, apply: bool, bg: bool) -> tuple[dict, str]:
    """Read (and with apply=True record) a statement file, with ONE undo for everything it changed."""
    from .security import undo

    from . import company, journal

    if apply:
        company.require("bank.import")
    company.require("budget.read")
    company.require("bills.read")  # the preview names the bills it would mark paid
    raw = Path(path).read_bytes()
    before_b, before_bu = B.snapshot(), BU.snapshot()

    def back():
        B.restore_all(before_b)
        BU.restore_all(before_bu)

    try:
        s = run(raw, apply)
    except Exception:
        if apply:
            back()  # all or nothing: a failure in the middle leaves no half import behind
        raise
    if apply and (s["added"] or s["bills"] or s["invoices"]):
        undo.push(f"import {Path(path).name}", back)
        journal.add("bank statement imported", f"{Path(path).name}: {s['added']} entries, {len(s['bills'])} bills, "
                    f"{len(s['invoices'])} invoices")
    return s, summary_text(s, bg, apply)

