"""Cash flow (issue #42): the weekly forecast from invoices, bills, repeating bills and the usual budget, the balance,
"can I afford", the fast answers, the tools, company roles and the app's API. Offline; every name, amount and date
is made up."""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, timedelta

os.environ["VAELON_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vaelon import bills as B, budget as BU, cashflow as CF, company, config, deals as D, intents, journal, server  # noqa: E402
from vaelon.config import Config  # noqa: E402
from vaelon.security import undo  # noqa: E402
from vaelon.tools import money, registry  # noqa: E402

registry.load_builtin()
OUT = tempfile.mkdtemp()
T = date(2026, 3, 2)  # a Monday
TODAY = date.today()


def fresh():
    for name in (B.FILE, BU.FILE, D.FILE, company.FILE, journal.FILE):
        (config.HOME / name).unlink(missing_ok=True)
    shutil.rmtree(config.HOME / "workspaces", ignore_errors=True)
    company._session.update({"user": None, "workspace": company.PERSONAL})
    company._fails.clear()
    company.system(False)
    undo._stack.clear()


def invoice(client, cents, issued, due_days):
    B.set_profile(name="Test Studio")
    return B.new_invoice({"name": client}, [{"desc": "Design work", "qty": "1", "price": cents}], vat_rate="0",
                         due_days=due_days, issued=issued, lang="en")


def ask(text):
    hit = intents.detect(text)
    return hit.answer if hit else None


class Forecast(unittest.TestCase):
    def setUp(self):
        fresh()

    def test_weeks_balance_late_undated_apart_and_deals(self):
        BU.set_balance(100000, T)
        invoice("Acme Test", 50000, T - timedelta(days=20), 10)  # due 20 Feb: late, counted this week
        invoice("Globex Test", 30000, T, 10)  # due 12 March
        B.add_bill("Power Test", 5000, "EUR", T - timedelta(days=5))  # late
        B.add_bill("Rent Test", 120000, "EUR", T + timedelta(days=14))
        B.add_bill("Water Test", 2000, "EUR", None)  # no due date
        B.add_bill("Hosting Test", 1000, "USD", T + timedelta(days=3))  # not converted
        D.add("Initech Test", "website", 100000, "EUR", "proposal", close=T + timedelta(days=18))
        D.add("Lost Test", "app", 900000, "EUR", "lost", close=T + timedelta(days=5))
        f = CF.forecast(28, T)
        self.assertEqual([w["from"] for w in f["weeks"]], ["2026-03-02", "2026-03-09", "2026-03-16", "2026-03-23"])
        self.assertEqual(f["weeks"][-1]["to"], "2026-03-29")
        self.assertEqual([(w["in"], w["out"]) for w in f["weeks"]], [(50000, 5000), (30000, 0), (0, 120000), (0, 0)])
        self.assertEqual([w["balance"] for w in f["weeks"]], [145000, 175000, 55000, 55000])
        self.assertEqual((f["in_total"], f["out_total"], f["late_in"], f["late_out"]), (80000, 125000, 50000, 5000))
        self.assertEqual(f["undated_out"], 2000)
        self.assertEqual(f["apart"], {"USD": -1000})
        self.assertEqual([(p["client"], p["weighted"]) for p in f["possible"]], [("Initech Test", 50000)])
        self.assertEqual(f["lowest"], {"balance": 55000, "week": "2026-03-16"})
        self.assertEqual((f["balance"], f["balance_on"], f["short_week"]), (100000, "2026-03-02", ""))
        late = [x for x in f["items"] if x["late"]]
        self.assertTrue(all(x["date"] == "2026-03-02" for x in late))
        text = CF.text(f)
        for part in ("Cash flow for the next 28 days (EUR)", "Late invoices", "Late bills", "without a due date",
                     "NOT counted", "USD", "lowest 550.00"):
            self.assertIn(part, text.replace(" ", " "))

    def test_the_last_day_is_counted(self):
        B.add_bill("Last Day Test", 7000, "EUR", T + timedelta(days=27))
        f = CF.forecast(28, T)
        self.assertEqual(f["out_total"], 7000)
        B.add_bill("Too Late Test", 9000, "EUR", T + timedelta(days=28))
        self.assertEqual(CF.forecast(28, T)["out_total"], 7000)

    def test_short_week_warning(self):
        BU.set_balance(10000, T)
        B.add_bill("Big Bill Test", 20000, "EUR", T + timedelta(days=8))
        f = CF.forecast(30, T)
        self.assertEqual(f["short_week"], "2026-03-09")
        self.assertEqual(f["lowest"]["balance"], -10000)
        self.assertIn("WARNING: money may run short in the week of 2026-03-09", CF.text(f))

    def test_no_balance_shows_the_change_only(self):
        B.add_bill("Rent Test", 40000, "EUR", T + timedelta(days=2))
        f = CF.forecast(30, T)
        self.assertIsNone(f["balance"])
        self.assertIsNone(f["lowest"])
        self.assertEqual(f["short_week"], "")  # no warning without a real balance
        self.assertIn("Tell me your current balance", CF.text(f))

    def test_repeating_bills_are_estimates(self):
        B.add_bill("Rent Test", 80000, "EUR", T + timedelta(days=8), repeat="monthly")
        f = CF.forecast(60, T)
        rent = [x for x in f["items"] if x["label"] == "Rent Test"]
        self.assertEqual([x["date"] for x in rent], ["2026-03-10", "2026-04-10"])
        self.assertEqual([x["estimate"] for x in rent], [False, True])
        self.assertIn("Estimates included", CF.text(f))

    def test_paid_and_void_are_left_out(self):
        b = B.add_bill("Paid Test", 5000, "EUR", T + timedelta(days=1))
        B.mark_paid(b["id"], T)
        inv = invoice("Void Test", 9000, T, 5)
        B.update_invoice(inv["id"], status="void")
        f = CF.forecast(30, T)
        self.assertEqual((f["in_total"], f["out_total"]), (0, 0))

    def test_usual_income_and_spending_of_the_last_three_months(self):
        BU.add("income", 300000, "EUR", "salary", "salary", on=date(2026, 1, 15))
        BU.add("expense", 90000, "EUR", "groceries", "food", on=date(2026, 2, 10))
        BU.add("expense", 777700, "EUR", "groceries", "this month - not counted", on=date(2026, 3, 1))
        BU.add("expense", 555500, "EUR", "groceries", "too old - not counted", on=date(2025, 11, 20))
        self.assertEqual(CF._usual(T, "EUR"), (150000, 45000))  # two months have entries
        f = CF.forecast(28, T)
        usual = [x for x in f["items"] if x["source"] == "usual"]
        self.assertEqual(len(usual), 8)
        self.assertTrue(all(x["estimate"] for x in usual))
        self.assertEqual(f["in_total"], 4 * round(150000 * 7 / 30.44))

    def test_signed_cents(self):
        self.assertEqual(CF.signed_cents("-150,50"), -15050)
        self.assertEqual(CF.signed_cents("− 5"), -500)
        self.assertEqual(CF.signed_cents("2 000"), 200000)
        with self.assertRaises(ValueError):
            CF.signed_cents("lots")

    def test_afford(self):
        BU.set_balance(100000, T)
        B.add_bill("Rent Test", 45000, "EUR", T + timedelta(days=3))
        yes = CF.afford(50000, 30, T)
        self.assertTrue(yes["ok"])
        self.assertEqual(yes["lowest_after"], 5000)
        no = CF.afford(60000, 30, T)
        self.assertFalse(no["ok"])
        self.assertEqual(no["lowest_after"], -5000)
        BU.set_balance(None)
        self.assertFalse(CF.afford(100, 30, T)["known"])

    def test_a_series_is_counted_once(self):
        B.add_bill("Power Test", 4500, "EUR", T + timedelta(days=3), repeat="monthly")  # 5 March
        B.add_bill("Power Test", 4700, "EUR", T + timedelta(days=34), repeat="monthly")  # 5 April, the real next one
        f = CF.forecast(90, T)
        power = [(x["date"], x["amount"]) for x in f["items"] if x["label"] == "Power Test"]
        self.assertEqual(power, [("2026-03-05", 4500), ("2026-04-05", 4700), ("2026-05-05", 4700)])

    def test_two_subscriptions_of_one_vendor_are_two_series(self):
        B.add_bill("Phone Co Test", 2000, "EUR", T + timedelta(days=3), repeat="monthly")  # the 5th
        B.add_bill("Phone Co Test", 3500, "EUR", T + timedelta(days=18), repeat="monthly")  # the 20th
        f = CF.forecast(90, T)
        phone = sorted((x["date"], x["amount"]) for x in f["items"] if x["label"] == "Phone Co Test")
        self.assertEqual(phone, [("2026-03-05", 2000), ("2026-03-20", 3500), ("2026-04-05", 2000),
                                 ("2026-04-20", 3500), ("2026-05-05", 2000), ("2026-05-20", 3500)])

    def test_the_real_next_bill_on_another_day_continues_the_series(self):
        B.add_bill("Power Test", 4500, "EUR", T + timedelta(days=3), repeat="monthly")  # 5 March
        B.add_bill("Power Test", 4700, "EUR", T + timedelta(days=41), repeat="monthly")  # 12 April (moved by a week)
        f = CF.forecast(90, T)
        power = sorted((x["date"], x["amount"]) for x in f["items"] if x["label"] == "Power Test")
        self.assertEqual(power, [("2026-03-05", 4500), ("2026-04-12", 4700), ("2026-05-12", 4700)])

    def test_one_real_bill_stands_for_one_payment_only(self):
        B.add_bill("Water Test", 3000, "EUR", T + timedelta(days=3), repeat="monthly")  # 5 March
        B.add_bill("Water Test", 3100, "EUR", T + timedelta(days=41))  # 12 April, one-off: it IS April's payment
        f = CF.forecast(90, T)
        water = sorted((x["date"], x["amount"]) for x in f["items"] if x["label"] == "Water Test")
        self.assertEqual(water, [("2026-03-05", 3000), ("2026-04-12", 3100), ("2026-05-05", 3000)])  # May still counted

    def test_the_1st_and_the_17th_are_two_series(self):
        B.add_bill("Flat Test", 40000, "EUR", date(2026, 3, 1), repeat="monthly", category="rent")
        B.add_bill("Flat Test", 40000, "EUR", date(2026, 3, 17), repeat="monthly", category="rent")
        f = CF.forecast(60, T)
        self.assertEqual(sorted(x["date"] for x in f["items"] if x["source"] == "repeat"), ["2026-04-01", "2026-04-17"])

    def test_a_one_off_bill_takes_the_nearest_payment_of_its_own_kind(self):
        B.add_bill("Telco Test", 1000, "EUR", date(2026, 3, 5), repeat="monthly", category="rent")
        B.add_bill("Telco Test", 2000, "EUR", date(2026, 3, 20), repeat="monthly", category="rent")
        B.add_bill("Telco Test", 2000, "EUR", date(2026, 4, 19), category="rent")  # the real April bill of the 20th
        B.add_bill("Telco Test", 3000, "EUR", date(2026, 4, 6), category="water")  # another kind: replaces nothing
        f = CF.forecast(60, T)
        rep = sorted((x["date"], x["amount"]) for x in f["items"] if x["source"] == "repeat")
        self.assertEqual(rep, [("2026-04-05", 1000)])  # 20 April is the real bill of the 19th

    def test_a_correction_mid_month_is_not_next_months_bill(self):
        B.add_bill("Power Test", 4500, "EUR", date(2026, 3, 5), repeat="monthly")
        B.add_bill("Power Test", 900, "EUR", date(2026, 3, 20))  # a one-off correction, 15 days BEFORE 5 April
        f = CF.forecast(40, T)
        self.assertEqual([x["date"] for x in f["items"] if x["source"] == "repeat"], ["2026-04-05"])

    def test_the_31st_then_the_1st_is_one_series(self):
        B.add_bill("Rent Test", 50000, "EUR", date(2026, 1, 31), repeat="monthly")
        B.add_bill("Rent Test", 50000, "EUR", date(2026, 3, 1), repeat="monthly")
        f = CF.forecast(40, T)
        self.assertEqual(sorted(x["date"] for x in f["items"] if x["source"] == "repeat"), ["2026-04-01"])

    def test_two_equal_bills_do_not_double_the_series(self):
        for _ in range(2):  # the same bill typed twice by mistake
            B.add_bill("Gym Test", 3000, "EUR", T + timedelta(days=3), repeat="monthly")
        f = CF.forecast(60, T)
        self.assertEqual(len([x for x in f["items"] if x["source"] == "repeat"]), 1)  # 5 April once

    def test_a_forgotten_series_is_late_not_new(self):
        B.add_bill("Phone Test", 2000, "EUR", date(2025, 12, 10), repeat="monthly")  # never marked paid
        f = CF.forecast(30, T)
        phone = [x for x in f["items"] if x["label"] == "Phone Test"]
        self.assertEqual([x["date"] for x in phone], ["2026-03-02"] * 3 + ["2026-03-10"])  # Dec, Jan, Feb late; March
        self.assertEqual([x["late"] for x in phone], [True, True, True, False])
        self.assertEqual(f["late_out"], 6000)

    def test_a_dip_inside_a_week_is_seen(self):
        BU.set_balance(50000, T)
        B.add_bill("Rent Test", 100000, "EUR", T + timedelta(days=1))  # Tuesday
        invoice("Acme Test", 200000, T, 4)  # Friday
        f = CF.forecast(30, T)
        self.assertEqual(f["weeks"][0]["balance"], 150000)  # the week ends fine ...
        self.assertEqual(f["short_week"], "2026-03-02")  # ... but Tuesday to Friday is below zero
        self.assertEqual(f["lowest"], {"balance": -50000, "week": "2026-03-02"})
        self.assertFalse(CF.afford(100, 30, T)["ok"])

    def test_one_month_of_budget_is_not_divided_by_three(self):
        BU.add("expense", 60000, "EUR", "groceries", "food", on=date(2026, 2, 10))
        self.assertEqual(CF._usual(T, "EUR"), (0, 60000))

    def test_undated_bill_in_another_currency_is_listed_apart(self):
        B.add_bill("Tool Test", 1500, "USD", None)
        f = CF.forecast(30, T)
        self.assertEqual((f["undated_out"], f["apart"]), (0, {"USD": -1500}))

    def test_an_old_balance_is_pointed_out(self):
        BU.set_balance(1000, T - timedelta(days=20))
        self.assertIn("20 days old", CF.text(CF.forecast(30, T)))

    def test_days_are_clamped(self):
        self.assertEqual(CF.forecast(1, T)["days"], 7)
        self.assertEqual(CF.forecast(5000, T)["days"], 366)


class Words(unittest.TestCase):
    def setUp(self):
        fresh()

    def test_fast_answers(self):
        self.assertTrue(ask("how does my cash flow look?").startswith("Cash flow for the next 90 days"))
        self.assertTrue(ask("cash flow for the next 30 days").startswith("Cash flow for the next 30 days"))
        self.assertIn("I need the money you have now", ask("can I afford 50 EUR?"))
        BU.set_balance(10000)
        self.assertTrue(ask("can I afford 50 EUR?").startswith("Yes"))
        B.add_bill("Rent Test", 20000, "EUR", TODAY + timedelta(days=5))
        self.assertTrue(ask("can I afford 2000 EUR next month?").startswith("Not safely"))
        self.assertIsNone(ask("can I afford a holiday?"))  # no amount: the model answers
        self.assertTrue(ask("can I afford a new laptop for 50 EUR next week?").startswith("Not safely"))
        for q in ("can I afford a 600 EUR fridge?", "can I afford a 300 EUR monitor?", "can I afford 50 EUR now?",
                  "can I afford a 300 EUR phone this month?"):
            self.assertTrue(ask(q).startswith(("Yes", "Not safely")), q)  # plain words, not months or days

    def test_bigger_questions_go_to_the_model(self):
        for q in ("cash flow vs profit: what is the difference?", "Cash flow statement explained",
                  "how is my cash flow calculated?", "cashflow is important for startups, explain why",
                  "can I afford a house with a salary of 3000 EUR?", "could I afford to retire at 50 with 500000 EUR",
                  "can I afford 3 days off?", "can I afford 500 EUR by 15.12?",
                  "can I afford 2000 EUR a month for rent?", "can I afford 100 EUR every week?",
                  "can I afford 100 EUR daily?", "can I afford 2000 EUR weekly?", "can I afford 2000 EUR next year?",
                  "can I afford a 2000 EUR vacation in July?", "can I afford 2000 EUR by Friday?",
                  "can I afford 5000 EUR in debt?", "can I afford 500 EUR on credit?",
                  "can I afford 500 EUR after rent?"):
            self.assertIsNone(ask(q), q)

    def test_horizon_words(self):
        for words, n in (("for the next 6 months", 180), ("for the next 2 weeks", 14), ("next month", 30),
                         ("this quarter", 90), ("in 45 days", 45), ("over two months", 60), ("", 90)):
            self.assertEqual(intents._horizon(words, 90), n, words)
        self.assertTrue(ask("how's my cash flow looking for the next 2 weeks?").startswith("Cash flow for the next 14 days"))

    def test_router_words(self):
        from vaelon import router

        self.assertIn("money", router.groups_for("how does my cash flow look?"))
        self.assertIn("money", router.groups_for("can I afford 2000 EUR next month?"))
        for text in ("my balance is 2000 EUR", "set my balance to -150 EUR", "show me the cash flow"):
            self.assertIn("money", router.groups_for(text), text)
        for text in ("affordable housing in big cities", "work-life balance tips", "best cashback cards",
                     "balance is key in life"):
            self.assertNotIn("money", router.groups_for(text), text)

    def test_budget_currency_change_converts_the_balance(self):
        BU.set_balance(100000)
        with self.assertRaisesRegex(ValueError, "balance"):
            BU.set_currency("USD")  # no exact rate: refused, 1000 EUR never silently becomes 1000 USD
        self.assertEqual((BU.load()["currency"], BU.load()["balance"]["cents"]), ("EUR", 100000))

    def test_tools(self):
        self.assertIn("cashflow_forecast", registry.PRIVATE_TOOLS)
        out = money.cashflow_balance(None, "-150,50")
        self.assertIn("-150.50", out.replace(" ", " "))
        self.assertEqual(BU.load()["balance"]["cents"], -15050)
        undo.undo()
        self.assertIsNone(BU.load()["balance"])
        self.assertTrue(money.cashflow_forecast(None, days="30").startswith("Cash flow for the next 30 days"))
        self.assertIn("I need the current balance", money.cashflow_forecast(None, afford="100"))
        BU.set_balance(100000)
        self.assertIn("next 90 days", money.cashflow_forecast(None, days=90, afford="100 EUR"))
        self.assertIn("next 30 days", money.cashflow_forecast(None, afford="100 EUR"))
        self.assertIn("no exact rate for USD", money.cashflow_forecast(None, afford="100 USD"))
        self.assertTrue(money.cashflow_forecast(None, afford="2,000 EUR").startswith("Not safely"))  # 2000 > 1000
        for amount in ("€2,000", "EUR 2,000", "€1,200", "a TV for €2,000"):  # never read as 2 or 1 euro
            self.assertTrue(money.cashflow_forecast(None, afford=amount).startswith("Not safely"), amount)
        self.assertTrue(money.cashflow_forecast(None, afford="€500").startswith("Yes"))
        self.assertIn("no exact rate for USD", money.cashflow_forecast(None, afford="USD 1,500"))  # never read as EUR


class Roles(unittest.TestCase):
    def setUp(self):
        fresh()
        company.enable("Owner One", "1234")
        self.acme = company.add_workspace("Acme Ltd")
        for name, role, pin in (("Sam Sales", "sales", "3333"), ("Mo Member", "member", "5555"),
                                ("Vic Viewer", "viewer", "4444"), ("Ann Accountant", "accountant", "2222")):
            company.add_user(name, role, pin, [self.acme["id"]])

    def tearDown(self):
        fresh()

    def as_(self, name, pin):
        company.sign_in(next(u["id"] for u in company.users() if u["name"] == name), pin)

    def test_who_may_see_and_set_it(self):
        for name, pin in (("Sam Sales", "3333"), ("Mo Member", "5555")):
            self.as_(name, pin)
            with self.assertRaises(company.Denied):
                CF.forecast(30)
        self.as_("Vic Viewer", "4444")
        self.assertEqual(CF.forecast(30)["days"], 30)
        with self.assertRaises(company.Denied):
            BU.set_balance(5000)
        self.as_("Ann Accountant", "2222")
        BU.set_balance(5000)
        self.assertEqual(CF.forecast(30)["balance"], 5000)
        self.assertTrue(any("balance set" in e.get("action", "") for e in journal.read()))


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
        self.assertEqual(self.call("GET", "/budget?view=cashflow", token=False)[0], 401)
        self.assertEqual(self.call("GET", "/budget?view=cashflow", origin="https://evil.example")[0], 403)
        code, f = self.call("GET", "/budget?view=cashflow&days=30")
        self.assertEqual((code, f["days"], f["balance"]), (200, 30, None))
        self.assertEqual(self.call("GET", "/budget?view=cashflow&days=abc")[1]["days"], 90)
        self.assertEqual(self.call("POST", "/budget", {"action": "balance", "amount": "-150,50"})[0], 200)
        self.assertEqual(self.call("GET", "/budget?view=cashflow")[1]["balance"], -15050)
        self.assertEqual(self.call("POST", "/budget", {"action": "balance", "amount": ""})[0], 200)
        self.assertIsNone(self.call("GET", "/budget?view=cashflow")[1]["balance"])
        self.assertEqual(self.call("POST", "/budget", {"action": "balance", "amount": "lots"})[0], 400)
        self.assertIn("entries", self.call("GET", "/budget")[1])  # the budget view is unchanged

    def test_a_role_without_the_rights_gets_403(self):
        company.enable("Owner One", "1234")
        acme = company.add_workspace("Acme Ltd")
        company.add_user("Mo Member", "member", "5555", [acme["id"]])
        try:
            company.sign_in(next(u["id"] for u in company.users() if u["name"] == "Mo Member"), "5555")
            self.assertEqual(self.call("GET", "/budget?view=cashflow")[0], 403)
            self.assertEqual(self.call("GET", "/budget")[0], 200)  # the plain budget is still theirs
        finally:
            fresh()


if __name__ == "__main__":
    unittest.main()
