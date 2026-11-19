"""Bank statements (CSV) and life events: three statement shapes, bill / invoice matching, no double import, leva ->
euro, formula text stays text in Excel; exams -> calendar + study plan, birthdays, name days, anniversaries,
a forgotten birthday. Offline; every name, amount and line is made up."""
import os
import re
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ["VAELON_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vaelon import agenda as A, bankcsv, bills as B, budget as BU, config, intents, life  # noqa: E402
from vaelon.config import Config  # noqa: E402
from vaelon.security import undo  # noqa: E402
from vaelon.tools import registry  # noqa: E402

registry.load_builtin()
OUT = Path(tempfile.mkdtemp())
T = date.today()
D1, D2, D3 = (T - timedelta(days=k) for k in (3, 2, 1))

BG_BANK = ("Извлечение по сметка\nПериод;{a} - {c}\n\nДата;Основание;Дебит;Кредит;Валута\n"
           "{a};Плащане EVN Електроснабдяване;62,52;;EUR\n{b};Lidl България 125;23,40;;EUR\n"
           "{b};Заплата ноември;;2 500,00;EUR\n{c};Kaufland 34;19,60;;BGN\n").format(
    a=D1.strftime("%d.%m.%Y"), b=D2.strftime("%d.%m.%Y"), c=D3.strftime("%d.%m.%Y"))
REVOLUT = ("Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance\n"
           f"CARD_PAYMENT,Current,{D1} 10:00:00,{D1} 10:01:00,Shell,-45.00,0.00,EUR,COMPLETED,100.00\n"
           f"CARD_PAYMENT,Current,{D2} 10:00:00,{D2} 10:01:00,Coffee Bar,-3.50,0.00,EUR,REVERTED,100.00\n"
           f"TRANSFER,Current,{D3} 09:00:00,{D3} 09:01:00,Payment from Acme Ltd inv 7,744.00,0.00,EUR,COMPLETED,844.00\n")
SIGNED = ("Date\tDetails\tAmount\tD/C\tCurrency\n"
          f"{D1}\t=HYPERLINK(\"http://example.invalid\")\t10.00\tD\tEUR\n{D2}\tRefund shop\t5,00\tC\tEUR\n")


def fresh():
    for f in (B.FILE, BU.FILE, A.FILE, "deals.enc"):
        (config.HOME / f).unlink(missing_ok=True)
    undo._stack.clear()


def ask(text):
    hit = intents.detect(text)
    return hit.answer if hit else None


class Statements(unittest.TestCase):
    def setUp(self):
        fresh()

    def test_a_bulgarian_bank_in_windows_1251(self):
        tx = bankcsv.parse(BG_BANK.encode("cp1251"))
        self.assertEqual([(t["date"], t["amount"], t["currency"]) for t in tx],
                         [(D1, -6252, "EUR"), (D2, -2340, "EUR"), (D2, 250000, "EUR"), (D3, -1002, "EUR")])  # 19,60 лв -> 10,02 €
        self.assertEqual(tx[1]["text"], "Lidl България 125")

    def test_revolut_skips_reverted_and_a_sign_column(self):
        self.assertEqual([t["amount"] for t in bankcsv.parse(REVOLUT.encode())], [-4500, 74400])
        self.assertEqual([t["amount"] for t in bankcsv.parse(SIGNED.encode())], [-1000, 500])
        with self.assertRaises(ValueError):
            bankcsv.parse(b"just,some,words\n1,2,3\n")

    def test_bills_and_invoices_are_matched_and_nothing_is_imported_twice(self):
        bill = B.add_bill("EVN", 6252, "EUR", D1 + timedelta(days=5))
        B.set_profile(name="Test Studio Ltd", vat_rate="20")
        inv = B.new_invoice({"name": "Acme Ltd"}, B.parse_items("Design | 1 | 620"))
        p = OUT / "bg.csv"
        p.write_bytes(BG_BANK.encode("cp1251"))
        s, text = bankcsv.import_file(p, apply=False, bg=True)
        self.assertEqual((s["expenses"], s["income"], [b["vendor"] for b in s["bills"]]), (2, 1, ["EVN"]))
        self.assertIn("Да ги внеса ли?", text)
        self.assertEqual(BU.load()["entries"], [])  # a preview changes nothing
        s, text = bankcsv.import_file(p, apply=True, bg=True)
        self.assertEqual(B.get_bill(bill["id"])["status"], "paid")
        self.assertEqual(B.get_bill(bill["id"])["paid_on"], D1.isoformat())
        cats = sorted(e["category"] for e in BU.load()["entries"] if e["kind"] == "expense")
        self.assertEqual(cats, ["groceries", "groceries"])
        s, _ = bankcsv.import_file(p, apply=True, bg=True)
        self.assertEqual((s["skipped"], s["added"], s["bills"]), (4, 0, []))  # the second time: nothing new
        r = OUT / "revolut.csv"
        r.write_bytes(REVOLUT.encode())
        s, _ = bankcsv.import_file(r, apply=True, bg=False)
        self.assertEqual([i["number"] for i in s["invoices"]], [inv["number"]])
        self.assertEqual(B.find_invoice(inv["number"])["status"], "paid")
        undo.undo()  # the Revolut import as a whole
        self.assertEqual(B.find_invoice(inv["number"])["status"], "unpaid")

    def test_the_tool_and_formula_text_in_excel(self):
        p = OUT / "signed.csv"
        p.write_bytes(SIGNED.encode())
        c = registry.Ctx(Config(allowed_roots=[str(OUT)], output_dir=str(OUT)), approver=lambda r: True)
        c.extra["lang"] = "en"
        out = registry.execute(c, "bank_import", {"path": str(p)})
        self.assertIn("money out: 1", out)
        self.assertTrue(c.tainted)
        out = registry.execute(registry.Ctx(Config(allowed_roots=[str(OUT)], output_dir=str(OUT)), approver=lambda r: True),
                               "money_export", {"period": "this year"})
        import openpyxl

        ws = openpyxl.load_workbook(re.search(r"created (.+?\.xlsx)", out).group(1))["Budget"]
        notes = [ws.cell(row=r, column=6) for r in range(2, ws.max_row + 1)]
        bad = next(n for n in notes if str(n.value).startswith("=HYPERLINK"))
        self.assertEqual(bad.data_type, "s")  # text, never a formula

    def test_an_attached_statement_goes_to_the_import(self):
        self.assertTrue(intents.BANK_RX.search("внеси извлечението"))
        self.assertTrue(intents.BANK_RX.search("import this bank statement"))


class LifeEvents(unittest.TestCase):
    def setUp(self):
        fresh()

    def test_exam_then_study_plan(self):
        a = ask("имам изпит по математика след 3-4 дни")
        self.assertTrue(a.startswith("Записах: Изпит по математика") and "по-ранния ден" in a and "план за учене" in a, a)
        ex = life.next_exam()
        self.assertEqual((ex["when"].date() - T).days, 3)
        self.assertTrue(ex["all_day"])
        a = ask("теми: дроби, уравнения, проценти; 1 час на ден")
        self.assertTrue(a.startswith("Планът (по 60 мин на ден от 18:00"), a)
        study = [e for e in A.load() if e.get("notes") == "study plan"]
        self.assertTrue(study and all(e["title"].startswith("Учене (математика)") for e in study))
        self.assertIn("пробен изпит", study[-1]["title"])
        self.assertTrue(all(A.parse_iso(e["start"]).date() < ex["when"].date() for e in study))
        a = ask("I have a history exam on Friday at 9")
        self.assertTrue(a.startswith("Saved: Exam: history"), a)
        a = ask("topics: WW1, WW2 and the Cold War; 45 min a day at 19")
        self.assertIn("45 min a day at 19:00", a)
        self.assertTrue(any(e["title"].startswith("Study (history)") for e in A.load()))  # the exam saved last
        self.assertIsNone(ask("имам тест"))  # no date: the model asks

    def test_the_plan_spreads_topics(self):
        plan, ids = life.study_plan("bio", T + timedelta(days=6), ["a", "b", "c", "d", "e", "f", "g"], 30, "17:00",
                                    today=T)
        self.assertEqual(plan[-1][1], "mock exam + review of the weak spots")
        self.assertEqual(sorted(x for _, w in plan[:-1] for x in w.split(", ") if not w.startswith("review")),
                         ["a", "b", "c", "d", "e", "f", "g"])
        self.assertEqual(len(ids), len(plan))
        with self.assertRaises(ValueError):
            life.study_plan("x", T, ["a"])

    def test_birthdays_name_days_anniversaries(self):
        self.assertTrue(ask("рожденият ден на мама е на 12 март").startswith("Записах: Рожден ден: мама - 12 март, всяка година."))
        self.assertTrue(ask("Ivan's birthday is on 3 April").startswith("Saved: Birthday: Ivan - 3 April"))
        self.assertIn("Имен ден: Иван", ask("имен ден на Иван е на 7 януари"))
        self.assertIn("Нашата годишнина", ask("годишнината ни е на 20 юни"))
        evs = {e["title"]: e for e in A.load()}
        mum = evs["Рожден ден: мама"]
        self.assertEqual((mum["repeat"], mum["all_day"], mum["remind"]), ("yearly", True, life.DAY_BEFORE_9))
        start = A.parse_iso(mum["start"]).date()
        self.assertTrue(T <= start < T + timedelta(days=366))
        # the reminder comes at 09:00 the day before
        fired = A.fire_due(datetime.combine(start - timedelta(days=1), datetime.min.time()).replace(hour=9, minute=0), toast=False)
        self.assertEqual(fired, ["Рожден ден: мама tomorrow"])

    def test_a_forgotten_birthday(self):
        a = ask("забравих рождения ден на Петър, беше вчера")
        self.assertIn("от догодина ще ти напомням", a)
        ev = next(e for e in A.load() if e["title"] == "Рожден ден: Петър")
        self.assertEqual(A.parse_iso(ev["start"]).date(), (T - timedelta(days=1)).replace(year=T.year + 1))
        self.assertIn("When is Ana's birthday?", ask("I forgot Ana's birthday"))


if __name__ == "__main__":
    unittest.main()
