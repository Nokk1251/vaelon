"""Every finding of the code review of 2026-11-15, as a test that keeps it fixed. Offline, temporary data folder,
every name and amount made up."""
import os
import re
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

os.environ["VAELON_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vaelon import agenda as A, bankcsv, bills as B, budget as BU, config, deals as D, intents, life  # noqa: E402
from vaelon.security import undo  # noqa: E402
from vaelon.tools import create  # noqa: E402

T = date.today()
OUT = Path(tempfile.mkdtemp())


def fresh():
    for f in (B.FILE, BU.FILE, D.FILE, A.FILE):
        (config.HOME / f).unlink(missing_ok=True)
    undo._stack.clear()


def ask(text):
    hit = intents.detect(text)
    return hit.answer if hit else None


class QuestionsNeverWrite(unittest.TestCase):  # HIGH-1, MEDIUM-1
    def setUp(self):
        fresh()

    def test_questions_and_a_bill_that_arrived(self):
        bill = B.add_bill("EVN", 6000, "EUR", T + timedelta(days=3), "electricity")
        for q in ("платих ли тока?", "платих ли тока", "did I pay the electricity bill", "похарчих ли 50 евро за храна?",
                  "имам ли изпит?", "рожденият ден на мама е на 12 март?", "спечелихме ли Acme?"):
            ask(q)
        self.assertEqual(B.get_bill(bill["id"])["status"], "unpaid")
        self.assertEqual(BU.load()["entries"], [])
        self.assertEqual(A.load(), [])
        self.assertIsNone(ask("получих сметка за ток 45 евро"))  # a bill arrived: no income
        self.assertEqual(BU.load()["entries"], [])

    def test_an_amount_must_match_the_bill(self):
        tax = B.add_bill("Данък", 12000, "EUR", T + timedelta(days=3), "taxes & fees")
        a = ask("I paid 15 euros for a taxi")
        self.assertEqual(B.get_bill(tax["id"])["status"], "unpaid")
        self.assertTrue(a.startswith("Expense recorded: 15.00 EUR for transport"), a)
        self.assertEqual(B.category_of("apples"), "other")
        self.assertEqual(B.category_of("викторина"), "other")
        water = B.add_bill("Софийска вода", 1890, "EUR", T + timedelta(days=3), "water")
        ask("платих 2 евро за вода")  # a bottle of water, not the water bill
        self.assertEqual(B.get_bill(water["id"])["status"], "unpaid")
        self.assertTrue(ask("платих водата 18,90 евро").startswith("Отбелязах като платена: Софийска вода"))


class Statements(unittest.TestCase):  # HIGH-2, HIGH-3, MEDIUM-2, LOW-2
    def setUp(self):
        fresh()

    def write(self, name, text):
        p = OUT / name
        p.write_text(text, "utf-8")
        return p

    def test_another_currency_is_shown_and_never_half_imported(self):
        d = T.strftime("%Y-%m-%d")
        p = self.write("huf.csv", f"Date,Description,Amount,Currency\n{d},Shop,-10.00,EUR\n{d},Budapest cafe,-2000,HUF\n{d},Shop two,-5.00,EUR\n")
        s, text = bankcsv.import_file(p, apply=False, bg=False)
        self.assertEqual((s["expenses"], s["other"]), (2, {"HUF": 200000}))
        self.assertIn("in another currency (not imported)", text)
        s, _ = bankcsv.import_file(p, apply=True, bg=False)
        self.assertEqual(len(BU.load()["entries"]), 2)
        undo.undo()
        self.assertEqual(BU.load()["entries"], [])

    def test_a_failure_in_the_middle_leaves_nothing(self):
        d = T.strftime("%Y-%m-%d")
        p = self.write("x.csv", f"Date,Description,Amount\n{d},A,-1.00\n{d},B,-2.00\n")
        real = BU.add
        calls = []

        def broken(*a, **k):
            calls.append(1)
            if len(calls) == 2:
                raise ValueError("boom")
            return real(*a, **k)
        BU.add = broken
        try:
            with self.assertRaises(ValueError):
                bankcsv.import_file(p, apply=True, bg=False)
        finally:
            BU.add = real
        self.assertEqual(BU.load()["entries"], [])

    def test_equal_lines_on_one_day_are_kept(self):
        d = T.strftime("%d.%m.%Y")
        p = self.write("coffee.csv", f"Дата;Описание;Сума\n{d};Coffee Bar;-2,50\n{d};Coffee Bar;-2,50\n{d};Coffee Bar;-2,50\n")
        s, _ = bankcsv.import_file(p, apply=True, bg=True)
        self.assertEqual(s["added"], 3)
        s, _ = bankcsv.import_file(p, apply=True, bg=True)
        self.assertEqual((s["added"], s["skipped"]), (0, 3))

    def test_matching_needs_more_than_the_amount(self):
        phone = B.add_bill("A1 България", 2500, "EUR", T, "internet & phone")
        B.set_profile(name="Test Studio Ltd", vat_rate="0")
        zeta = B.new_invoice({"name": "Zeta Corp"}, B.parse_items("Work | 1 | 100"))
        d = T.strftime("%Y-%m-%d")
        p = self.write("m.csv", f"Date,Description,Amount\n{d},Restaurant Happy,-25.00\n{d},Beta Ltd ref 2026-11,100.00\n")
        s, _ = bankcsv.import_file(p, apply=True, bg=False)
        self.assertEqual((s["bills"], s["invoices"]), ([], []))
        self.assertEqual(B.get_bill(phone["id"])["status"], "unpaid")
        self.assertEqual(B.find_invoice(zeta["number"])["status"], "unpaid")
        p = self.write("m2.csv", f"Date,Description,Amount\n{d},A1 Bulgaria monthly,-25.00\n{d},Payment Zeta Corp,100.00\n")
        s, _ = bankcsv.import_file(p, apply=True, bg=False)
        self.assertEqual(([b["vendor"] for b in s["bills"]], [i["client"] for i in s["invoices"]]), (["A1 България"], ["Zeta Corp"]))

    def test_small_reading_details(self):
        tx = bankcsv.parse("Date;Text;Amount;Currency\n1.11.2026 10:00;Shop;−12,50;EURO\nbad date;x;1;EUR\n".encode())
        self.assertEqual((tx[0]["date"], tx[0]["amount"], tx[0]["currency"], tx[0]["unread"]), (date(2026, 11, 1), -1250, "EUR", 1))


class Words(unittest.TestCase):  # MEDIUM-3, MEDIUM-4, MEDIUM-5, MEDIUM-6, LOW-3, LOW-4, LOW-5
    def setUp(self):
        fresh()

    def test_a_decimal_is_not_a_date(self):
        a = ask("купих 2.5 кг ябълки за 4 евро")
        self.assertTrue(a.startswith("Записах разход: 4,00 евро"), a)
        self.assertEqual(BU.load()["entries"][0]["date"], T.isoformat())

    def test_deal_stages_only_from_plain_statements(self):
        d = D.add("Acme", "site", 100000, "EUR", "negotiation")
        for s in ("Cancel the meeting with Acme.", "Ivan will lead the Acme project", "говорихме с Acme за цената",
                  "Acme is in Sofia"):
            ask(s)
        self.assertEqual(D.get(d["id"])["stage"], "negotiation")
        self.assertIsNone(ask("Acme is a lead"))  # a step back needs a plain "move"
        self.assertIn("[lead]", ask("move Acme to lead"))
        self.assertIn("[оферта]", ask("Acme е на оферта"))
        self.assertIn("[спечелена]", ask("спечелихме Acme"))
        self.assertIn("[lost]", ask("Acme said no"))

    def test_study_plan_only_from_a_list(self):
        ask("имам изпит по химия след 5 дни")
        n = len(A.load())
        for s in ("Влизат ли дробите в изпита?", "The topic is too hard for me"):
            self.assertIsNone(ask(s))
        self.assertEqual(len(A.load()), n)
        a = ask("теми: задачи от 10 до 20, реакции")
        self.assertIn("от 18:00", a)  # "от 10" is not a time
        a = ask("темите са: окисление; 45 мин на ден в 7")
        self.assertIn("от 07:00", a)

    def test_study_plan_guards(self):
        plan, _ = life.study_plan("x", T + timedelta(days=3), ["a"], 5000, "00:00")
        evs = [e for e in A.load() if e.get("notes") == "study plan"]
        self.assertTrue(all(e["minutes"] == 480 for e in evs))
        self.assertTrue(all(A.parse_iso(e["start"]).date() > T for e in evs))  # 00:00 today is already gone
        with self.assertRaises(ValueError):
            life.study_plan("x", T + timedelta(days=3), ["a"], 60, "25:00")

    def test_29_february(self):
        a = ask("рожденият ден на Ана е на 29 февруари")
        self.assertTrue(a.startswith("Записах: Рожден ден: Ана"), a)
        ev = next(e for e in A.load() if e["title"] == "Рожден ден: Ана")
        d = A.parse_iso(ev["start"]).date()
        self.assertEqual(d.month, 2)
        self.assertIn(d.day, (28, 29))

    def test_merchant_categories(self):
        for text, cat in (("BOOKING.COM", "travel"), ("METRO Cash & Carry", "groceries"), ("кока-кола", "other"),
                          ("business lunch", "eating out"), ("Uber trip", "transport")):
            self.assertEqual(BU.category_of(text), cat, text)

    def test_excel_numbers(self):
        self.assertEqual(create._num("1.200 €")[0], 1200)
        self.assertEqual(create._num("1.234.567")[0], 1234567)
        self.assertEqual(create._num("0,125")[0], 0.125)
        self.assertEqual(create._num("45,20 €"), (45.2, "money"))


class Files(unittest.TestCase):  # LOW-1 and the unreadable-file risk
    def setUp(self):
        fresh()

    def test_formula_titles_and_headers_stay_text(self):
        import openpyxl

        create.write_table_xlsx(OUT / "f.xlsx", "=1+1", [["=HYPERLINK(1)", "Sum"], ["a", "1"], ["b", "2"]], "none")
        ws = openpyxl.load_workbook(OUT / "f.xlsx").active
        self.assertEqual((ws["A1"].data_type, ws["A4"].data_type), ("s", "s"))

    def test_an_unreadable_file_is_never_overwritten(self):
        B.add_bill("Keep me", 100, "EUR", T)
        p = config.HOME / B.FILE
        p.write_text("not a vault blob", "utf-8")
        with self.assertRaises(RuntimeError):
            B.add_bill("New", 200, "EUR", T)
        self.assertEqual(p.read_text("utf-8"), "not a vault blob")  # untouched
        self.assertEqual(B.load()["bills"], [])  # reading still works (shows nothing) without harm
        (config.HOME / D.FILE).write_text("broken", "utf-8")
        with self.assertRaises(RuntimeError):
            D.add("x")
        self.assertEqual((config.HOME / D.FILE).read_text("utf-8"), "broken")


if __name__ == "__main__":
    unittest.main()
