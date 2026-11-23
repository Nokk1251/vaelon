"""Bills and invoices as tools (vaelon/bills.py keeps the data). Vaelon never pays anything: it keeps the list,
reminds, reads bills from files and writes invoices. The clear cases ("платих тока", "what bills do I have") are
answered by intents without the model."""
from __future__ import annotations

import datetime as _dtm

from .. import bills as B
from ..security.policy import Risk
from .registry import tool


IMAGE_QUESTION = ("This is a bill or an invoice. Copy these lines exactly as printed: the company that issued it, "
                  "the invoice number, the total amount to pay with its currency, and the due date (payment deadline).")


def _bg(ctx) -> bool:
    return getattr(ctx, "extra", {}).get("lang") == "bg"


def _undo(label: str, before: dict) -> None:
    from ..security import undo

    undo.push(label, lambda: B.restore_all(before))


def _date(text: str, field: str) -> _dtm.date | None:
    if not str(text or "").strip():
        return None
    d, _ = B.find_date(str(text))
    if d is None:
        raise ValueError(f"I could not read the {field}. Use e.g. '25.11', '2026-11-25', '25 November'.")
    return d


def _amount(text) -> tuple[int, str]:
    hit = B.find_amount(str(text))
    if not hit:
        raise ValueError("I could not read the amount. Use e.g. '45.20', '45,20 евро', '€30'.")
    return hit[0], hit[1]


@tool("bill_add", "Add a bill to pay (electricity, rent, a supplier's invoice ...). Vaelon reminds before the due date. "
      "It NEVER pays - paying is the user's job.",
      {"vendor": "who it is from / what it is for", "amount": "e.g. '45.20', '45,20 EUR', '€30'",
       "?due": "due date, e.g. '25.11'", "?category": "electricity, water, heating, internet & phone, rent, insurance, "
       "taxes & fees, subscriptions, loan, supplier, other (guessed if empty)", "?number": "the bill's number",
       "?notes": "details", "?repeat": "monthly / quarterly / yearly", "?remind": "days before the due date (default 3, 'no' = none)"},
      risk=Risk.REVERSIBLE, group="money")
def bill_add(ctx, vendor, amount, due="", category="", number="", notes="", repeat="", remind=""):
    before = B.snapshot()
    c, cur = _amount(amount)
    rem = None if str(remind).strip().lower() in ("no", "none", "off", "не", "без", "0") else (
        int(str(remind).strip()) if str(remind).strip().isdigit() else 3)
    b = B.add_bill(vendor, c, cur, _date(due, "due date"), category, number, notes, B.repeat_of(repeat), rem)
    _undo(f"add bill {b['vendor']}", before)
    return f"added [id {b['id']}]: {B.bill_line(b, _bg(ctx), ids=False)}"


@tool("bills_list", "List bills: 'unpaid' (default, overdue first), 'paid' or 'all'", {"?status": "unpaid / paid / all"},
      group="money")
def bills_list(ctx, status="unpaid"):
    from .. import company

    company.require("bills.read")
    st = str(status or "unpaid").lower().strip()
    from .registry import outside_shown

    if st.startswith("un") or st in ("", "open", "due"):
        outside_shown(ctx, B.unpaid())
        return B.unpaid_text(_bg(ctx))
    items = [b for b in B.load()["bills"] if st == "all" or b["status"] == "paid"]
    items.sort(key=lambda b: b.get("paid_on") or b["due"] or b["added"], reverse=True)
    outside_shown(ctx, items[:40])
    return "\n".join("• " + B.bill_line(b, _bg(ctx)) for b in items[:40]) or "no bills"


@tool("bill_paid", "Mark a bill as PAID in the list after the user paid it (this does not pay anything). "
      "`bill`: its id or words like 'electricity'.", {"bill": "id or words", "?date": "when it was paid (default today)"},
      risk=Risk.REVERSIBLE, group="money")
def bill_paid(ctx, bill, date=""):
    target = B.get_bill(str(bill).strip()) or next(iter(B.match(str(bill))), None)
    if not target:
        return "ERROR: no unpaid bill matches that (see bills_list)"
    before = B.snapshot()
    done = B.mark_paid(target["id"], _date(date, "date"))
    _undo(f"mark {target['vendor']} paid", before)
    b, nxt = done
    out = f"marked paid: {B.bill_line(b, _bg(ctx), ids=False)}"
    if nxt:
        out += f". Next one expected: {B.bill_line(nxt, _bg(ctx), ids=False)}"
    return out


@tool("bill_update", "Change a bill: its amount, due date, vendor, category, number, notes, repeat or reminder",
      {"id": "bill id", "?amount": "new amount", "?due": "new due date", "?vendor": "new name", "?category": "category",
       "?number": "bill number", "?notes": "notes", "?repeat": "monthly / quarterly / yearly / none", "?remind": "days before"},
      risk=Risk.REVERSIBLE, group="money")
def bill_update(ctx, id, amount="", due="", vendor="", category="", number="", notes="", repeat="", remind=""):
    b = B.get_bill(str(id).strip())
    if not b:
        return "ERROR: no bill with that id"
    ch: dict = {}
    if str(amount).strip():
        ch["amount"], ch["currency"] = _amount(amount)
        ch["estimate"] = False
    if str(due).strip():
        ch["due"], ch["alerted"] = _date(due, "due date").isoformat(), ""
    if str(vendor).strip():
        ch["vendor"] = str(vendor).strip()[:120]
    if str(category).strip():
        ch["category"] = B.category_of(category)
    for k, v in (("number", number), ("notes", notes)):
        if str(v).strip():
            ch[k] = str(v).strip()[:500]
    if str(repeat).strip():
        ch["repeat"] = B.repeat_of(repeat)
    if str(remind).strip():
        ch["remind"] = None if not str(remind).strip().isdigit() else min(60, int(remind))
    if not ch:
        return "nothing to change"
    before = B.snapshot()
    b = B.update_bill(b["id"], **ch)
    _undo(f"change bill {b['vendor']}", before)
    return f"changed: {B.bill_line(b, _bg(ctx), ids=False)}"


@tool("bill_delete", "Remove a bill from the list (entered by mistake)", {"id": "bill id"}, risk=Risk.REVERSIBLE,
      group="money", summary=lambda a: f"DELETE bill {a.get('id')}")
def bill_delete(ctx, id):
    before = B.snapshot()
    gone = B.delete_bill(str(id).strip())
    if not gone:
        return "ERROR: no bill with that id"
    _undo(f"delete bill {gone['vendor']}", before)
    return f"removed: {gone['vendor']}"


@tool("bill_from_file", "Read a bill or invoice from a PDF / Word file or a photo and add it to the bills to pay "
      "(vendor, amount, due date and number are read from it). Untrusted content.",
      {"path": "the file", "?repeat": "monthly / quarterly / yearly"}, risk=Risk.REVERSIBLE, untrusted=True, group="money")
def bill_from_file(ctx, path, repeat=""):
    from ..security.injection import fence
    from ..security.policy import resolve_path
    from .perception import _read_any

    p = resolve_path(str(path), ctx.cfg.allowed_roots)
    if not p.is_file():
        return "ERROR: no such file"
    if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"):
        from .perception import look_at_image

        raw = look_at_image(ctx, str(p), IMAGE_QUESTION)
    else:
        raw = _read_any(p, 20000)
    found = B.scan(raw)
    missing = [k for k in ("vendor", "amount", "due") if not found.get(k)]
    if found["amount"] is None:
        return fence(f"I could not find the amount to pay in {p.name}. Missing: {', '.join(missing)}. "
                     "Ask the user for the amount and use bill_add.", f"bill:{p.name}")[0]
    before = B.snapshot()
    b = B.add_bill(found["vendor"] or p.stem, found["amount"], found["currency"] or "EUR", found["due"],
                   found["category"], found["number"], f"read from {p.name}", B.repeat_of(repeat), 3, file=str(p))
    _undo(f"add bill {b['vendor']}", before)
    note = f" Not found in the file: {', '.join(missing)} - ask the user." if missing else ""
    return fence(f"added [id {b['id']}] from {p.name}: {B.bill_line(b, _bg(ctx), ids=False)}.{note} "
                 "Tell the user what was read so they can correct it.", f"bill:{p.name}")[0]


@tool("bills_summary", "Spending on bills by category, what is still to pay and the invoices issued, for a period: "
      "'this month', 'last month', 'this year' (default), '2025', 'November'", {"?period": "which period"}, group="money")
def bills_summary(ctx, period=""):
    from .. import company

    company.require("bills.read")
    frm, to, label = B.period(str(period))
    return B.summary(frm, to, label, _bg(ctx))


@tool("money_export", "Save bills, invoices, budget entries and deals as an Excel file (for an accountant)", {"?period": "e.g. 'this year', 'last month'"},
      risk=Risk.REVERSIBLE, group="money")
def money_export(ctx, period=""):
    from .. import company

    company.require("export")
    from .create import _save

    from .. import budget

    frm, to, label = B.period(str(period) or "this year")
    bills, invoices = B.export_rows(frm, to)
    from .. import deals

    spending = budget.export_rows(frm, to)
    pipeline = deals.export_rows()
    if len(bills) == 1 and len(invoices) == 1 and len(spending) == 1 and len(pipeline) == 1:
        return f"there are no bills, invoices, budget entries or deals for {label}"
    return _save(ctx, f"Vaelon money {label}", ".xlsx", lambda p: B.write_xlsx(p, bills, invoices, spending, pipeline))


@tool("business_profile", "Show or set the user's business details printed on invoices (name, address, company number, "
      "VAT number, contact person, bank details, VAT rate, the next invoice number). No arguments = show them.",
      {"?name": "business name", "?address": "address", "?company_id": "company number (ЕИК)", "?vat_id": "VAT number",
       "?person": "responsible person (МОЛ)", "?bank": "bank details as the user gave them", "?email": "e-mail",
       "?phone": "phone", "?vat_rate": "percent, e.g. 20 or 0", "?next": "the next invoice number"},
      risk=Risk.REVERSIBLE, group="money")
def business_profile(ctx, **fields):
    fields = {k: v for k, v in fields.items() if str(v).strip()}
    if not fields:
        from .. import company

        if not (company.can("bills.read") or company.can("invoices.read")):
            company.require("invoices.read")
        me = B.profile()
        return "\n".join(f"{k}: {v}" for k, v in me.items()) or "no business details yet"
    before = B.snapshot()
    me = B.set_profile(**fields)
    _undo("change business details", before)
    return "saved business details: " + ", ".join(sorted(k for k in fields))


def make_invoice(ctx, client: dict, items: list[dict], vat_rate=None, due_days=14, currency="", notes="", lang="") -> tuple[dict, str]:
    """Number + store + PDF. Returns (invoice, the _save message)."""
    from .create import _save

    before = B.snapshot()
    inv = B.new_invoice(client, items, vat_rate, due_days, currency, notes, lang or ("bg" if _bg(ctx) else "en"))
    try:
        holder = {}

        def write(p):
            B.invoice_pdf(inv, p)
            holder["path"] = str(p)

        msg = _save(ctx, f"Invoice {inv['number']} {client.get('name', '')}", ".pdf", write)
    except Exception:
        B.restore_all(before)  # no PDF -> the number is not used up
        raise
    B.update_invoice(inv["id"], file=holder.get("path", ""))
    inv["file"] = holder.get("path", "")
    _undo(f"invoice {inv['number']}", before)
    return inv, msg


@tool("invoice_create", "Issue an invoice to a client as a PDF (numbered automatically). Items: one per line, "
      "'description | quantity | unit price' (or 'Design 500', '3 x Consulting 150').",
      {"client": "client's name", "items": "the items", "?client_address": "client's address",
       "?client_company_id": "client's company number (ЕИК)", "?client_vat_id": "client's VAT number",
       "?vat_rate": "percent (default from business details)", "?due_days": "days to pay (default 14)",
       "?currency": "EUR (default), USD, GBP, CHF", "?notes": "a note printed on it", "?language": "bg or en"},
      risk=Risk.REVERSIBLE, group="money")
def invoice_create(ctx, client, items, client_address="", client_company_id="", client_vat_id="", vat_rate="",
                   due_days="14", currency="", notes="", language=""):
    parsed = B.parse_items(str(items))
    days = int(str(due_days).strip()) if str(due_days).strip().isdigit() else 14
    inv, msg = make_invoice(ctx, {"name": client, "address": client_address, "company_id": client_company_id,
                                  "vat_id": client_vat_id}, parsed, vat_rate or None, days, currency, notes,
                            "en" if str(language).lower().startswith("en") else "bg" if str(language).lower().startswith("bg") else "")
    net, vat, total = B.invoice_totals(inv)
    return (f"invoice no. {inv['number']} for {inv['client']['name']}: {B.money(total, inv['currency'])} "
            f"(net {B.money(net, inv['currency'])}, VAT {inv['vat_rate']} %), due {inv['due']}. {msg}")


@tool("invoices_list", "List the invoices the user issued: 'unpaid' (default - who owes money), 'paid', 'all'",
      {"?status": "unpaid / paid / all"}, group="money")
def invoices_list(ctx, status="unpaid"):
    from .. import company

    company.require("invoices.read")
    st = str(status or "unpaid").lower()
    if st.startswith("un") or st in ("", "open"):
        return B.owed_text(_bg(ctx))
    items = [i for i in B.load()["invoices"] if st == "all" or i["status"] == st]
    return "\n".join("• " + B.invoice_line(i, _bg(ctx)) for i in sorted(items, key=lambda i: i["number"], reverse=True)[:40]) or "no invoices"


@tool("invoice_paid", "Mark an issued invoice as paid by the client", {"invoice": "its number or id", "?date": "when (default today)"},
      risk=Risk.REVERSIBLE, group="money")
def invoice_paid(ctx, invoice, date=""):
    inv = B.find_invoice(str(invoice))
    if not inv or inv["status"] == "void":
        return "ERROR: no such invoice (see invoices_list)"
    before = B.snapshot()
    inv = B.update_invoice(inv["id"], status="paid", paid_on=(_date(date, "date") or _dtm.date.today()).isoformat())
    _undo(f"invoice {inv['number']} paid", before)
    return f"marked paid: {B.invoice_line(inv, _bg(ctx), ids=False)}"


@tool("invoice_void", "Void (cancel) an issued invoice. It is not deleted: the number stays used and a VOID copy is made.",
      {"invoice": "its number or id"}, risk=Risk.REVERSIBLE, group="money",
      summary=lambda a: f"VOID invoice {a.get('invoice')}")
def invoice_void(ctx, invoice):
    from .create import _save

    inv = B.find_invoice(str(invoice))
    if not inv:
        return "ERROR: no such invoice"
    if inv["status"] == "void":
        return "it is already void"
    before = B.snapshot()
    inv = B.update_invoice(inv["id"], status="void")
    _undo(f"void invoice {inv['number']}", before)
    msg = _save(ctx, f"Invoice {inv['number']} VOID", ".pdf", lambda p: B.invoice_pdf(inv, p))
    return f"invoice no. {inv['number']} is void. {msg}"


# ---------------------------------------------------------------- the budget (vaelon/budget.py)
from .. import budget as _bu


def _undo_budget(label: str, before: dict) -> None:
    from ..security import undo

    undo.push(label, lambda: _bu.restore_all(before))


@tool("expense_add", "Record money the user spent (groceries, fuel, a coffee ...) in the budget. A bill marked paid is "
      "counted already - do not add it twice.",
      {"amount": "e.g. '30 EUR', '12.50 EUR'", "?category": "groceries, eating out, transport, car, shopping, health, "
       "entertainment, education, gifts, travel, home, kids, pets, personal care or a bill category (guessed if empty)",
       "?note": "what it was", "?date": "when (default today)"}, risk=Risk.REVERSIBLE, group="money")
def expense_add(ctx, amount, category="", note="", date=""):
    c, cur = _amount(amount)
    before = _bu.snapshot()
    e = _bu.add("expense", c, cur, str(category), str(note), _date(date, "date"))
    _undo_budget("add expense", before)
    return f"recorded [id {e['id']}]: {_bu.entry_line(e, _bg(ctx))}.{_bu.warning(e['category'], _bg(ctx), on=e.get('date'))}"


@tool("income_add", "Record money the user received (salary, a payment, a refund) in the budget",
      {"amount": "e.g. '2000 EUR'", "?note": "what it was", "?date": "when (default today)"}, risk=Risk.REVERSIBLE, group="money")
def income_add(ctx, amount, note="", date=""):
    c, cur = _amount(amount)
    before = _bu.snapshot()
    e = _bu.add("income", c, cur, "", str(note), _date(date, "date"))
    _undo_budget("add income", before)
    return f"recorded [id {e['id']}]: {_bu.entry_line(e, _bg(ctx))}"


@tool("budget_set", "Set a monthly limit for a spending category ('total' = all spending). amount 'none' removes it.",
      {"category": "e.g. groceries, eating out, total", "amount": "e.g. '400 EUR' or 'none'"}, risk=Risk.REVERSIBLE, group="money")
def budget_set(ctx, category, amount):
    before = _bu.snapshot()
    if str(amount).strip().lower() in ("none", "no", "remove", "off", "без", "махни"):
        r = _bu.set_limit(str(category), None)
        _undo_budget("remove limit", before)
        return f"removed the limit for {r['category']}"
    c, cur = _amount(amount)
    v = _bu.convert(c, cur, _bu.load()["currency"])
    if v is None:
        return f"ERROR: the budget is kept in {_bu.load()['currency']}; give the limit in that currency"
    r = _bu.set_limit(str(category), v)
    _undo_budget("set limit", before)
    return f"monthly limit for {r['category']}: {B.money(v, _bu.load()['currency'])}"


@tool("budget_report", "The budget for a month: income, spending by category against the limits, what is left. "
      "With a category: only that one.", {"?month": "'this month' (default), 'last month', 'October', '2026-10'",
                                          "?category": "one category"}, group="money")
def budget_report(ctx, month="", category=""):
    from .. import company

    company.require("budget.read")
    cat = _bu.category_of(str(category)) if str(category).strip() else ""
    return _bu.report(_bu.month_of(str(month)), _bg(ctx), "" if cat == "other" else cat)


@tool("budget_entries", "List the expenses and income recorded for a month (with ids)", {"?month": "which month"}, group="money")
def budget_entries(ctx, month=""):
    from .. import company

    company.require("budget.read")
    m = _bu.month(_bu.month_of(str(month)))
    from .registry import outside_shown

    outside_shown(ctx, m["entries"][:60])
    return "\n".join(f"{_bu.entry_line(e, _bg(ctx))}  [id {e['id']}]" for e in m["entries"][:60]) or "nothing recorded"


@tool("budget_entry_delete", "Remove an expense or income entry recorded by mistake", {"id": "entry id"},
      risk=Risk.REVERSIBLE, group="money", summary=lambda a: f"DELETE budget entry {a.get('id')}")
def budget_entry_delete(ctx, id):
    before = _bu.snapshot()
    gone = _bu.remove(str(id).strip())
    if not gone:
        return "ERROR: no entry with that id"
    _undo_budget("delete entry", before)
    return f"removed: {_bu.entry_line(gone, _bg(ctx))}"


# ---------------------------------------------------------------- deals (vaelon/deals.py)
from .. import deals as _dl


def _deal(key: str) -> dict:
    d = _dl.get(str(key).strip()) or next(iter(_dl.match(str(key))), None)
    if not d:
        raise ValueError("no deal matches that (see deals_list)")
    return d


def _undo_deals(label: str, before: list) -> None:
    from ..security import undo

    undo.push(label, lambda: _dl.restore_all(before))


@tool("deal_add", "Record a sales deal / opportunity: who the client is, what it is about, its value and stage "
      "(lead, contacted, proposal, negotiation, won, lost).",
      {"client": "the client (company or person)", "?title": "what is sold, e.g. 'website'", "?value": "e.g. '5000 EUR'",
       "?stage": "lead (default), contacted, proposal, negotiation, won, lost", "?close": "expected close date",
       "?next_step": "what to do next", "?next_date": "when (Vaelon reminds you that day)", "?contact": "contact person",
       "?note": "a note"}, risk=Risk.REVERSIBLE, group="money")
def deal_add(ctx, client, title="", value="", stage="", close="", next_step="", next_date="", contact="", note=""):
    c, cur = _amount(value) if str(value).strip() else (0, "EUR")
    st = _dl.stage_of(str(stage)) or "lead"
    before = _dl.snapshot()
    d = _dl.add(str(client), str(title), c, cur, st, _date(close, "close date"), str(next_step), _date(next_date, "date"),
                str(contact), str(note))
    _undo_deals(f"add deal {d['client']}", before)
    return f"added [id {d['id']}]: {_dl.deal_line(d, _bg(ctx), ids=False)}"


@tool("deals_list", "The sales pipeline: open deals by stage with values and next steps, late follow-ups, "
      "won / lost this year", {}, group="money")
def deals_list(ctx):
    from .. import company

    company.require("deals.read")
    return _dl.pipeline_text(_bg(ctx))


@tool("deal_update", "Change a deal: stage, value, title, expected close, next step and its date, contact, or add a note. "
      "`deal`: its id or the client's name.",
      {"deal": "id or client name", "?stage": "lead / contacted / proposal / negotiation / won / lost", "?value": "new value",
       "?title": "what it is about", "?close": "expected close date", "?next_step": "next step", "?next_date": "its date",
       "?contact": "contact person", "?note": "a note to add to its log"}, risk=Risk.REVERSIBLE, group="money")
def deal_update(ctx, deal, stage="", value="", title="", close="", next_step="", next_date="", contact="", note=""):
    d = _deal(deal)
    ch: dict = {}
    if str(stage).strip():
        st = _dl.stage_of(str(stage))
        if not st:
            return "ERROR: stage must be lead, contacted, proposal, negotiation, won or lost"
        ch["stage"] = st
    if str(value).strip():
        ch["value"], ch["currency"] = _amount(value)
    for k, v in (("title", title), ("next_step", next_step), ("contact", contact), ("note", note)):
        if str(v).strip():
            ch[k] = str(v).strip()
    if str(close).strip():
        ch["close"] = _date(close, "close date").isoformat()
    if str(next_date).strip():
        ch["next_date"] = _date(next_date, "date").isoformat()
    if not ch:
        return "nothing to change"
    before = _dl.snapshot()
    d = _dl.update(d["id"], **ch)
    _undo_deals(f"change deal {d['client']}", before)
    return f"changed: {_dl.deal_line(d, _bg(ctx), ids=False)}"


@tool("deal_won", "Mark a deal as WON. With invoice='yes' also issue its invoice (the deal's title and value as one line).",
      {"deal": "id or client name", "?invoice": "yes to make the invoice now"}, risk=Risk.REVERSIBLE, group="money")
def deal_won(ctx, deal, invoice=""):
    d = _deal(deal)
    before = _dl.snapshot()
    d = _dl.update(d["id"], stage="won")
    _undo_deals(f"won {d['client']}", before)
    out = f"won: {_dl.deal_line(d, _bg(ctx), ids=False)}"
    if str(invoice).strip().lower() in ("yes", "y", "true", "да", "1"):
        out += ". " + deal_invoice(ctx, d["id"])
    return out


@tool("deal_lost", "Mark a deal as LOST, with the reason if known", {"deal": "id or client name", "?reason": "why"},
      risk=Risk.REVERSIBLE, group="money")
def deal_lost(ctx, deal, reason=""):
    d = _deal(deal)
    before = _dl.snapshot()
    d = _dl.update(d["id"], stage="lost", lost_reason=str(reason).strip()[:200])
    _undo_deals(f"lost {d['client']}", before)
    return f"lost: {_dl.deal_line(d, _bg(ctx), ids=False)}"


@tool("deal_invoice", "Issue the invoice for a won deal (needs the business details and the deal's value)",
      {"deal": "id or client name"}, risk=Risk.REVERSIBLE, group="money")
def deal_invoice(ctx, deal):
    from .. import company

    company.require("invoices.write")
    company.require("deals.write")  # the invoice number is written on the deal: both rights, checked first
    d = _deal(deal)
    if d["stage"] != "won":
        return "ERROR: only a won deal is invoiced - mark it won first"
    if d.get("invoice"):
        return f"ERROR: it already has invoice no. {d['invoice']}"
    inv, msg = make_invoice(ctx, {"name": d["client"]}, _dl.invoice_items(d), None, 14, d["currency"])
    _dl.update(d["id"], invoice=inv["number"], note=f"invoice {inv['number']}")
    return f"invoice no. {inv['number']} for {d['client']}: {B.money(B.invoice_totals(inv)[2], inv['currency'])}. {msg}"


@tool("deal_delete", "Remove a deal entered by mistake (a lost deal should be marked lost instead)", {"deal": "id"},
      risk=Risk.REVERSIBLE, group="money", summary=lambda a: f"DELETE deal {a.get('deal')}")
def deal_delete(ctx, deal):
    before = _dl.snapshot()
    gone = _dl.remove(str(deal).strip())
    if not gone:
        return "ERROR: no deal with that id"
    _undo_deals(f"delete deal {gone['client']}", before)
    return f"removed: {gone['client']}"


@tool("bank_import", "Import a bank statement CSV (from online banking, Revolut, Wise) into the budget: payments that "
      "match an unpaid bill mark it paid, incoming payments that match an invoice mark it paid, the rest become "
      "expenses / income. Already imported lines are skipped. preview='yes' only shows what it would do.",
      {"path": "the .csv file", "?preview": "yes = only show"}, risk=Risk.REVERSIBLE, untrusted=True, group="money")
def bank_import(ctx, path, preview=""):
    from .. import bankcsv
    from ..security.injection import fence
    from ..security.policy import resolve_path

    p = resolve_path(str(path), ctx.cfg.allowed_roots)
    if p.suffix.lower() not in (".csv", ".txt") or not p.is_file():
        return "ERROR: give the statement as a .csv file"
    _s, text = bankcsv.import_file(p, apply=str(preview).strip().lower() not in ("yes", "y", "true", "да", "1"), bg=_bg(ctx))
    return fence(text, f"statement:{p.name}")[0]
