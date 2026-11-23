"""Deals: stages from words, the pipeline (weighted value, late and stale), follow-up reminders, the fast answers,
the tools (won -> invoice), the export and the app's API. Offline; every client, value and date is made up."""
import json
import os
import re
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ["VAELON_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vaelon import bills as B, config, deals as D, intents, reminders, router, server  # noqa: E402
from vaelon.config import Config  # noqa: E402
from vaelon.security import undo  # noqa: E402
from vaelon.tools import registry  # noqa: E402

registry.load_builtin()
OUT = tempfile.mkdtemp()
TODAY = date.today()
caught = []
reminders.notify = lambda title, text, kind="reminder", toast=True: caught.append((title, text)) or {}


def fresh():
    for f in (D.FILE, B.FILE, "budget.enc"):
        (config.HOME / f).unlink(missing_ok=True)
    undo._stack.clear()
    caught.clear()


def ask(text):
    hit = intents.detect(text)
    return hit.answer if hit else None


class Words(unittest.TestCase):
    def test_stages(self):
        cases = {"we won it": "won", "Acme signed": "won", "спечелихме": "won", "подписаха договора": "won",
                 "they said no": "lost", "Acme отказа": "lost", "загубихме": "lost", "send the proposal": "proposal",
                 "е на оферта": "proposal", "in negotiation": "negotiation", "преговори": "negotiation",
                 "we are in touch": "contacted", "a lead": "lead", "hello there": None}
        for text, st in cases.items():
            self.assertEqual(D.stage_of(text), st, text)


class Pipeline(unittest.TestCase):
    def setUp(self):
        fresh()

    def test_weighted_value_late_stale_and_win_rate(self):
        a = D.add("Acme", "website", 500000, "EUR", "proposal", next_step="send the offer", next_date=TODAY - timedelta(days=1))
        D.add("Globex", "app", 1200000, "EUR", "negotiation")
        old = D.add("Initech", "", 100000, "EUR", "lead")
        D.update(old["id"], updated=(TODAY - timedelta(days=20)).isoformat())
        self.assertEqual(D.weighted(a), 250000)
        text = D.pipeline_text(False, ids=False)
        self.assertIn("Open deals: 3, 18,000.00 EUR in total (11,600.00 EUR expected)", text)
        lines = text.splitlines()
        self.assertTrue(lines[1].startswith("• Globex - app") and lines[2].startswith("• Acme - website"))
        self.assertIn("LATE", lines[2])
        self.assertIn("Late next steps: Acme.", text)
        self.assertIn("No movement for 14+ days: Initech.", text)
        D.update(a["id"], stage="won")
        D.update(old["id"], stage="lost")
        text = D.pipeline_text(False)
        self.assertIn(f"In {TODAY.year}: won 1 (5,000.00 EUR), lost 1, win rate 50 %.", text)
        self.assertEqual(D.get(a["id"])["next_date"], "")  # a closed deal has no next step
        self.assertIn("успеваемост 50 %", D.pipeline_text(True))

    def test_match_prefers_the_named_client(self):
        a = D.add("Acme", "website")
        D.add("Acme Foods", "logo")
        self.assertEqual(D.match("the Acme deal")[0]["id"], a["id"])
        self.assertEqual(D.match("nothing"), [])

    def test_stored_encrypted_and_bad_values(self):
        D.add("Secret Client", "secret plan", 100)
        self.assertNotIn("Secret", (config.HOME / D.FILE).read_text("utf-8"))
        for kwargs in ({"client": ""}, {"client": "x", "stage": "maybe"}, {"client": "x", "currency": "XYZ"},
                       {"client": "x", "value": -1}):
            with self.assertRaises(ValueError):
                D.add(**kwargs)


class FollowUps(unittest.TestCase):
    def setUp(self):
        fresh()

    def test_next_step_day_and_a_passed_close_date_each_once(self):
        d = D.add("Acme", "website", next_step="call Ana", next_date=date(2026, 11, 20), close=date(2026, 11, 25))
        at = lambda day, h=10: datetime(2026, 11, day, h)  # noqa: E731
        self.assertEqual(D.fire_due(at(19)), [])
        self.assertEqual(D.fire_due(at(20, 6)), [])  # night
        self.assertEqual(D.fire_due(at(20)), ["Acme: call Ana (website)"])
        self.assertEqual(D.fire_due(at(21)), [])
        self.assertIn("expected close date (2026-11-25) has passed", D.fire_due(at(26))[0])
        self.assertEqual(D.fire_due(at(27)), [])
        D.update(d["id"], next_date="2026-11-28", next_step="send contract")
        self.assertEqual(D.fire_due(at(28)), ["Acme: send contract (website)"])
        D.update(d["id"], stage="won")
        self.assertEqual(D.fire_due(datetime(2026, 12, 1, 10)), [])
        self.assertEqual(len(caught), 3)


class FastAnswers(unittest.TestCase):
    def setUp(self):
        fresh()

    def test_add_move_follow_win_lose_list(self):
        self.assertEqual(ask("нова сделка с Acme: уеб сайт 5000 евро"), "Записах сделка: Acme - уеб сайт: 5 000,00 евро [потенциална].")
        self.assertEqual(ask("new deal with Globex for a mobile app 12000 EUR"), "Deal recorded: Globex - mobile app: 12,000.00 EUR [lead].")
        self.assertEqual(ask("new deal with Initech"), "Deal recorded: Initech: no value yet [lead].")
        self.assertEqual(ask("Acme е на оферта"), "Отбелязах: Acme - уеб сайт: 5 000,00 евро [оферта].")
        self.assertEqual(ask("move Globex to negotiation"), "Updated: Globex - mobile app: 12,000.00 EUR [negotiation].")
        a = ask("follow up with Globex on Friday about the contract")
        self.assertTrue(a.startswith("I will remind you on ") or a.startswith("I will remind you to"), a)
        self.assertIn("next: contract", a)
        a = ask("проследи Acme утре: да изпратя офертата")
        self.assertTrue(a.startswith("Ще ти напомня утре: Acme") and "следва: да изпратя офертата" in a, a)
        self.assertIn("Open deals: 3", ask("how are my deals going?"))
        a = ask("спечелихме Acme")
        self.assertTrue(a.startswith("Отбелязах: Acme - уеб сайт: 5 000,00 евро [спечелена]") and "фактура" in a, a)
        self.assertIsNone(ask("did we win Acme?"))  # a question changes nothing
        self.assertIsNone(ask("we won the lottery"))  # no deal named
        self.assertEqual(ask("Initech said no"), "Updated: Initech: no value yet [lost].")
        self.assertIn("успеваемост 50 %", ask("сделките ми"))
        self.assertTrue(ask("запиши среща с Acme в петък в 10").startswith("Записах в календара"))  # still the calendar
        undo.undo()  # the calendar event
        undo.undo()  # "Initech said no"
        self.assertEqual(D.match("Initech")[0]["stage"], "lead")

    def test_router(self):
        self.assertIn("deal_add", router.route("нова сделка с клиент"))
        self.assertIn("deals_list", router.route("show my pipeline"))


class Tools(unittest.TestCase):
    def setUp(self):
        fresh()

    def run_tool(self, name, args):
        c = registry.Ctx(Config(allowed_roots=[OUT], output_dir=OUT), approver=lambda r: True)
        c.extra["lang"] = "en"
        return registry.execute(c, name, args)

    def test_from_lead_to_invoice(self):
        out = self.run_tool("deal_add", {"client": "Acme Ltd", "title": "Website", "value": "5000 EUR", "next_date": "in 3 days",
                                         "next_step": "call"})
        self.assertTrue(out.startswith("added [id "), out)
        self.assertIn("proposal", self.run_tool("deal_update", {"deal": "acme", "stage": "offer sent", "note": "sent by e-mail"}))
        self.assertEqual(D.match("acme")[0]["notes"][-1]["text"], "sent by e-mail")
        self.assertIn("Acme Ltd - Website", self.run_tool("deals_list", {}))
        self.assertIn("ERROR", self.run_tool("deal_invoice", {"deal": "acme"}))  # not won yet
        B.set_profile(name="Test Studio Ltd", vat_rate="20")
        out = self.run_tool("deal_won", {"deal": "acme", "invoice": "yes"})
        self.assertIn("won:", out)
        self.assertIn("invoice no. 0000000001 for Acme Ltd: 6,000.00 EUR", out)
        pdf = re.search(r"created (.+?\.pdf)", out).group(1)
        self.assertTrue(Path(pdf).is_file())
        self.assertEqual(D.match("acme")[0]["invoice"], "0000000001")
        self.assertIn("already has invoice", self.run_tool("deal_invoice", {"deal": "acme"}))
        self.assertIn("lost:", self.run_tool("deal_add", {"client": "Globex"}) and self.run_tool("deal_lost", {"deal": "globex", "reason": "price"}))
        self.assertIn("(price)", self.run_tool("deals_list", {}) + D.deal_line(D.match("globex")[0], False))
        gid = D.match("globex")[0]["id"]
        self.assertTrue(self.run_tool("deal_delete", {"deal": gid}).startswith("removed"))
        out = self.run_tool("money_export", {"period": "this year"})
        import openpyxl

        wb = openpyxl.load_workbook(re.search(r"created (.+?\.xlsx)", out).group(1))
        self.assertIn("Deals", wb.sheetnames)
        self.assertEqual(wb["Deals"]["A2"].value, "Acme Ltd")


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
        self.assertEqual(self.call("GET", "/deals", token=False)[0], 401)
        code, r = self.call("POST", "/deals", {"action": "add", "client": "Acme", "title": "Website", "value": "5000",
                                               "stage": "proposal", "close": (TODAY + timedelta(days=30)).isoformat()})
        self.assertEqual(code, 200)
        did = r["deal"]["id"]
        o = self.call("GET", "/deals")[1]
        self.assertEqual((o["totals"]["count"], o["totals"]["open"], o["totals"]["expected"]), (1, {"EUR": 500000}, {"EUR": 250000}))
        nd = (TODAY + timedelta(days=2)).isoformat()
        self.assertEqual(self.call("POST", "/deals", {"action": "update", "id": did, "next_step": "call", "next_date": nd})[0], 200)
        self.assertEqual(self.call("POST", "/deals", {"action": "note", "id": did, "text": "they liked it"})[0], 200)
        d = self.call("GET", "/deals")[1]["deals"][0]
        self.assertEqual((d["next_date"], d["notes"][-1]["text"], d["chance"]), (nd, "they liked it", 50))
        self.assertEqual(self.call("POST", "/deals", {"action": "invoice", "id": did})[0], 400)  # not won
        self.assertEqual(self.call("POST", "/deals", {"action": "update", "id": did, "stage": "won"})[0], 200)
        B.set_profile(name="Test Studio Ltd", vat_rate="0")
        code, r = self.call("POST", "/deals", {"action": "invoice", "id": did})
        self.assertEqual(code, 200, r)
        self.assertTrue(Path(r["path"]).is_file() and Path(r["path"]).resolve().parent == Path(OUT).resolve())  # 8.3 short temp names (CI)
        self.assertEqual(self.call("GET", "/deals")[1]["deals"][0]["invoice"], "0000000001")
        for bad in ({"action": "add", "client": ""}, {"action": "add", "client": "x", "value": "lots"},
                    {"action": "add", "client": "x", "close": "soon"}, {"action": "update", "id": did, "stage": "maybe"},
                    {"action": "update", "id": "nope", "stage": "won"}, {"action": "note", "id": did, "text": ""},
                    {"action": "explode"}):
            self.assertEqual(self.call("POST", "/deals", bad)[0], 400, bad)
        self.assertEqual(self.call("POST", "/deals", {"action": "delete", "id": did}, origin="https://evil.example")[0], 403)
        self.assertEqual(self.call("POST", "/deals", {"action": "delete", "id": did})[0], 200)


if __name__ == "__main__":
    unittest.main()
