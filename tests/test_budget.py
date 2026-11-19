"""The budget: categories from words, income and expenses, limits and warnings, paid bills counted once, the
budget currency (euro; leva said or typed become euro, others apart), the fast answers, the tools and the app's API.
Offline; every amount and name is made up; nothing moves money."""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, timedelta

os.environ["VAELON_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vaelon import bills as B, budget as BU, config, intents, router, server  # noqa: E402
from vaelon.config import Config  # noqa: E402
from vaelon.security import undo  # noqa: E402
from vaelon.tools import registry  # noqa: E402

registry.load_builtin()
OUT = tempfile.mkdtemp()
TODAY = date.today()
FIRST = TODAY.replace(day=1)


def fresh():
    for f in (BU.FILE, B.FILE):
        (config.HOME / f).unlink(missing_ok=True)
    undo._stack.clear()


def ask(text):
    hit = intents.detect(text)
    return hit.answer if hit else None


class Words(unittest.TestCase):
    def test_categories(self):
        cases = {"Lidl": "groceries", "хляб и мляко": "groceries", "coffee": "eating out", "обяд": "eating out",
                 "бензин": "transport", "taxi": "transport", "аптека": "health", "кино": "entertainment",
                 "подарък за мама": "gifts", "хотел": "travel", "ток": "electricity", "наем": "rent",
                 "Netflix": "subscriptions", "something odd": "other"}
        for text, cat in cases.items():
            self.assertEqual(BU.category_of(text), cat, text)

    def test_months(self):
        d = date(2026, 11, 15)
        self.assertEqual(BU.month_of("", d), date(2026, 11, 1))
        self.assertEqual(BU.month_of("last month", d), date(2026, 10, 1))
        self.assertEqual(BU.month_of("миналия месец", date(2026, 1, 9)), date(2025, 12, 1))
        self.assertEqual(BU.month_of("декември", d), date(2025, 12, 1))
        self.assertEqual(BU.month_of("2026-03", d), date(2026, 3, 1))
        self.assertEqual(BU.month_label(date(2026, 11, 1), True), "ноември 2026")

    def test_exact_conversions_only(self):
        self.assertEqual(BU.convert(195583, "BGN", "EUR"), 100000)
        self.assertEqual(BU.convert(100000, "EUR", "BGN"), 195583)
        self.assertIsNone(BU.convert(1000, "USD", "EUR"))


class Month(unittest.TestCase):
    def setUp(self):
        fresh()

    def test_income_spending_limits_and_paid_bills_counted_once(self):
        BU.add("income", 250000, "EUR", note="salary")
        BU.add("expense", 3000, "BGN", note="Lidl")  # leva -> 15.34 EUR
        BU.add("expense", 1200, "EUR", note="coffee")
        BU.add("expense", 2000, "USD", note="app")  # cannot be converted: apart
        b = B.add_bill("Rent", 40000, "EUR", TODAY, "rent")
        B.mark_paid(b["id"])
        BU.set_limit("groceries", 40000)
        BU.set_limit("total", 100000)
        m = BU.month(FIRST)
        self.assertEqual((m["income"], m["spent"]), (250000, 1534 + 1200 + 40000))
        self.assertEqual(m["by_category"], {"groceries": 1534, "eating out": 1200, "rent": 40000})
        self.assertEqual(m["apart"], {"USD": 2000})
        text = BU.report(FIRST, False)
        self.assertIn("income 2,500.00 EUR, spent 427.34 EUR, 2,072.66 EUR left.", text)
        self.assertIn("• groceries: 15.34 EUR / 400.00 EUR (4 %)", text)
        self.assertIn("• rent: 400.00 EUR", text)
        self.assertIn("Overall limit: 427.34 EUR / 1,000.00 EUR (43 %)", text)
        self.assertIn("Not counted (other currency): 20.00 USD", text)
        self.assertIn("(paid bills are included)", text)
        bg = BU.report(FIRST, True, "groceries")
        self.assertEqual(bg, f"За храна през {BU.month_label(FIRST, True)}: похарчени 15,34 евро от 400,00 евро (4 %); остават 384,66 евро.")

    def test_warnings_at_80_percent_and_over_the_limit(self):
        BU.set_limit("eating out", 10000)
        BU.add("expense", 7000, "EUR", "eating out")
        self.assertEqual(BU.warning("eating out", False), "")
        BU.add("expense", 1500, "EUR", "eating out")
        self.assertIn("85 % of the limit", BU.warning("eating out", False))
        BU.add("expense", 2000, "EUR", "eating out")
        self.assertIn("over its limit (105.00 EUR of 100.00 EUR)", BU.warning("eating out", False))
        self.assertIn("над лимита", BU.warning("eating out", True))

    def test_changing_the_currency_converts_the_limits(self):
        BU.set_limit("groceries", 40000)
        BU.set_currency("EUR")
        self.assertEqual(BU.load()["limits"]["groceries"], 40000)
        for cur in ("XYZ", "BGN"):  # Bulgaria pays in euro: leva are no budget currency any more
            with self.assertRaises(ValueError):
                BU.set_currency(cur)

    def test_stored_encrypted_and_bad_values(self):
        BU.add("expense", 999, "EUR", note="Secret Shop")
        raw = (config.HOME / BU.FILE).read_text("utf-8")
        self.assertNotIn("Secret", raw)
        for args in (("expense", 0), ("loan", 100), ("expense", 100, "XYZ")):
            with self.assertRaises(ValueError):
                BU.add(*args)


class FastAnswers(unittest.TestCase):
    def setUp(self):
        fresh()

    def test_record_and_ask_in_both_languages(self):
        self.assertEqual(ask("бюджет за храна 400 евро на месец"), "Месечен лимит за храна: 400,00 евро.")
        self.assertEqual(ask("месечен бюджет 2000 евро"), "Общ месечен лимит за разходите: 2 000,00 евро.")
        self.assertEqual(ask("set a budget of 100 EUR for eating out"), "Monthly limit for eating out: 100.00 EUR.")
        self.assertEqual(ask("limit transport to 150 EUR"), "Monthly limit for transport: 150.00 EUR.")
        self.assertEqual(ask("получих заплата 2500 евро"), "Записах приход: 2 500,00 евро (заплата).")
        self.assertEqual(ask("got paid 300 EUR for a logo"), "Income recorded: 300.00 EUR (logo).")
        self.assertEqual(ask("похарчих 30 лв за храна"), "Записах разход: 15,34 евро за храна.")  # leva -> euro
        self.assertEqual(ask("купих хляб за 3 лв"), "Записах разход: 1,53 евро за храна (хляб).")
        self.assertEqual(ask("spent 12 EUR on coffee yesterday"), "Expense recorded: 12.00 EUR for eating out (coffee).")
        self.assertEqual(BU.load()["entries"][-1]["date"], (TODAY - timedelta(days=1)).isoformat())
        a = ask("spent 95 EUR on dinner")
        if TODAY.day > 1:  # yesterday's coffee is in this month too
            self.assertIn("Careful: eating out is over its limit (107.00 EUR of 100.00 EUR)", a)
        self.assertIsNone(ask("I spent 3 hours on this"))  # no money in it
        self.assertIsNone(ask("получих 3 имейла"))
        self.assertIsNone(ask("got 20 EUR from mum"))  # not clearly income: the model asks
        a = ask("как съм с бюджета?")
        self.assertTrue(a.startswith(BU.month_label(FIRST, True).capitalize() + ": приходи 2 800,00 евро"), a)
        self.assertIn("Общ лимит", a)
        self.assertIn("left", ask("how is my budget"))
        self.assertIn("остават 383,13 евро", ask("колко ми остава за храна"))
        self.assertIn("Eating out in", ask("how much is left for eating out?"))
        self.assertIn("приходи", ask("колко похарчих този месец"))
        self.assertIn("for eating out in", ask("how much did I spend on coffee this month?"))
        undo.undo()  # the last change was the dinner expense
        self.assertNotIn("dinner", [e["note"] for e in BU.load()["entries"]])

    def test_a_bill_payment_stays_a_bill_and_a_paid_bill_is_not_typed_twice(self):
        b = B.add_bill("EVN", 6000, "EUR", TODAY + timedelta(days=3))
        a = ask("платих тока")
        self.assertTrue(a.startswith("Отбелязах като платена"), a)  # the bill, not a new expense
        self.assertEqual(BU.load()["entries"], [])
        self.assertIn("ток", ask("колко похарчих този месец"))
        self.assertEqual(B.get_bill(b["id"])["status"], "paid")
        a = ask("платих 85 евро за ток")  # no unpaid electricity bill left: a plain expense
        self.assertEqual(a, "Записах разход: 85,00 евро за ток.")

    def test_router(self):
        self.assertIn("expense_add", router.route("похарчих много за храна"))
        self.assertIn("budget_report", router.route("how is my budget"))


class Tools(unittest.TestCase):
    def setUp(self):
        fresh()

    def run_tool(self, name, args):
        c = registry.Ctx(Config(allowed_roots=[OUT], output_dir=OUT), approver=lambda r: True)
        c.extra["lang"] = "en"
        return registry.execute(c, name, args)

    def test_tools(self):
        self.assertIn("monthly limit for groceries: 400.00 EUR", self.run_tool("budget_set", {"category": "groceries", "amount": "400 EUR"}))
        self.assertIn("ERROR", self.run_tool("budget_set", {"category": "groceries", "amount": "400 USD"}))
        out = self.run_tool("expense_add", {"amount": "350 EUR", "note": "Kaufland"})
        self.assertIn("-350.00 EUR groceries (Kaufland)", out)
        self.assertIn("88 % of the limit", out)
        self.assertIn("recorded", self.run_tool("income_add", {"amount": "2000 EUR", "note": "salary"}))
        self.assertIn("groceries: 350.00 EUR / 400.00 EUR", self.run_tool("budget_report", {}))
        self.assertIn("50.00 EUR left", self.run_tool("budget_report", {"category": "groceries"}))
        listing = self.run_tool("budget_entries", {})
        eid = listing.split("[id ")[1].split("]")[0]
        self.assertTrue(self.run_tool("budget_entry_delete", {"id": eid}).startswith("removed"))
        self.assertIn("removed the limit", self.run_tool("budget_set", {"category": "groceries", "amount": "none"}))
        out = self.run_tool("money_export", {"period": "this year"})
        import openpyxl
        import re

        wb = openpyxl.load_workbook(re.search(r"created (.+?\.xlsx)", out).group(1))
        self.assertIn("Budget", wb.sheetnames)


class Api(unittest.TestCase):
    def setUp(self):
        fresh()
        self.token = server.get_token()
        self.srv = server.serve(Config(provider="mock", output_dir=OUT, allowed_roots=[OUT]), port=0)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def call(self, method, path, body=None, token=True, origin=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None)
        if token:
            req.add_header("Authorization", f"Bearer {self.token}")
        if origin:
            req.add_header("Origin", origin)
        try:
            return 200, json.load(urllib.request.urlopen(req, timeout=20))
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            return e.code, json.loads(raw) if raw.startswith("{") else {}

    def test_the_tab(self):
        self.assertEqual(self.call("GET", "/budget", token=False)[0], 401)
        self.assertEqual(self.call("POST", "/budget", {"action": "limit", "category": "groceries", "amount": "100"})[0], 200)
        code, r = self.call("POST", "/budget", {"action": "add", "kind": "expense", "amount": "90,50", "note": "Lidl"})
        self.assertEqual((code, r["entry"]["category"]), (200, "groceries"))
        self.assertIn("91 % of the limit", r["warning"])
        self.assertEqual(self.call("POST", "/budget", {"action": "add", "kind": "income", "amount": "1000"})[0], 200)
        o = self.call("GET", f"/budget?month={FIRST:%Y-%m}")[1]
        self.assertEqual((o["income"], o["spent"], o["left"]), (100000, 9050, 90950))
        self.assertEqual(o["rows"], [{"category": "groceries", "spent": 9050, "limit": 10000}])
        eid = next(e["id"] for e in o["entries"] if e["kind"] == "expense")
        self.assertEqual(self.call("POST", "/budget", {"action": "delete", "id": eid})[0], 200)
        # a 100 EUR limit must not silently become 100 USD (no exact rate): refused until the limit is removed
        code, r = self.call("POST", "/budget", {"action": "currency", "currency": "USD"})
        self.assertEqual(code, 400)
        self.assertIn("cannot be converted exactly", r["error"])
        self.assertEqual(self.call("POST", "/budget", {"action": "limit", "category": "groceries", "amount": ""})[0], 200)
        self.assertEqual(self.call("POST", "/budget", {"action": "currency", "currency": "USD"})[0], 200)
        self.assertEqual(self.call("GET", "/budget")[1]["currency"], "USD")
        self.assertEqual(self.call("POST", "/budget", {"action": "currency", "currency": "BGN"})[0], 400)
        for bad in ({"action": "add", "amount": "lots"}, {"action": "add", "amount": "5", "date": "tomorrow"},
                    {"action": "delete", "id": "nope"}, {"action": "currency", "currency": "XYZ"},
                    {"action": "limit", "category": "groceries", "amount": "-5"}, {"action": "explode"}):
            self.assertEqual(self.call("POST", "/budget", bad)[0], 400, bad)
        self.assertEqual(self.call("POST", "/budget", {"action": "currency", "currency": "EUR"}, origin="https://evil.example")[0], 403)


if __name__ == "__main__":
    unittest.main()
