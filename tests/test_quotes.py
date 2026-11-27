"""Quotes (issue #43): lines read from words, their own Q- numbers, the PDF, the states and the expiry reminder,
accepted -> an invoice with the same lines and the deal won, the invoice numbering untouched until then, undo, the fast
answers, the tools, company roles and the app's API. Offline; every name, amount and date is made up."""
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

os.environ["VAELON_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vaelon import bills as B, company, config, deals as D, intents, journal, quotes as Q, reminders, router, server  # noqa: E402
from vaelon.config import Config  # noqa: E402
from vaelon.security import undo  # noqa: E402
from vaelon.tools import registry  # noqa: E402
from vaelon.security.policy import Risk  # noqa: E402

registry.load_builtin()
OUT = tempfile.mkdtemp()
TODAY = date.today()
caught = []
reminders.notify = lambda title, text, kind="reminder", toast=True: caught.append((title, text)) or {}


def fresh():
    for name in (B.FILE, D.FILE, Q.FILE, company.FILE, journal.FILE):
        (config.HOME / name).unlink(missing_ok=True)
    shutil.rmtree(config.HOME / "workspaces", ignore_errors=True)
    company._session.update({"user": None, "workspace": company.PERSONAL})
    company._fails.clear()
    company.system(False)
    undo._stack.clear()
    caught.clear()


def ctx(lang="en"):
    c = registry.Ctx(Config(allowed_roots=[OUT], output_dir=OUT), approver=lambda r: True)
    c.extra["lang"] = lang
    return c


def run(name, args):
    return registry.execute(ctx(), name, args)


def created(out: str) -> str:
    return re.search(r"created (.+?\.pdf)", out).group(1)


def ask(text):
    return intents.detect(text)


class Lines(unittest.TestCase):
    def test_words_to_lines(self):
        rows, cur = Q.items_from("10 hours of design at 60 EUR, hosting 120 EUR")
        self.assertEqual(rows, [{"desc": "Design (hours)", "qty": "10", "price": 6000},
                                {"desc": "Hosting", "qty": "1", "price": 12000}])
        self.assertEqual(cur, "EUR")
        rows, _ = Q.items_from("Logo | 2 | 150,50; 3 days of consulting at 400 each")
        self.assertEqual([(r["desc"], r["qty"], r["price"]) for r in rows],
                         [("Logo", "2", 15050), ("Consulting (days)", "3", 40000)])
        self.assertEqual(Q.items_from("Support 1,200 USD"), ([{"desc": "Support", "qty": "1", "price": 120000}], "USD"))
        self.assertEqual(B.parse_items("Design 1.250,50")[0]["price"], 125050)  # invoices read it the same way
        self.assertEqual(B.parse_items("Hosting 12 x 10")[0]["price"], 1000)
        self.assertEqual(B.parse_items("Room 1.101 rental 300")[0], {"desc": "Room 1.101 rental", "qty": "1", "price": 30000})
        self.assertEqual(B.parse_items("Stickers | 1,000 | 0,10")[0]["qty"], "1000")
        self.assertEqual(B.parse_items("Consulting | 1,5 | 100")[0]["qty"], "1.5")
        with self.assertRaises(ValueError):
            Q.items_from("design 100 EUR; hosting 20 USD")  # one currency per quote
        with self.assertRaises(ValueError):
            Q.items_from("something nice")

    def test_two_lines_and_the_usual_ways_of_saying_them(self):
        for text, want in (
                ("10 hours of design at 60 EUR, 5 hours of testing at 40 EUR", [("Design (hours)", "10", 6000), ("Testing (hours)", "5", 4000)]),
                ("10 hours of design at 60 EUR plus 5 hours of testing at 40 EUR", [("Design (hours)", "10", 6000), ("Testing (hours)", "5", 4000)]),
                ("2 logos at 150 EUR, 10 hours of design at 60 EUR", [("Logos", "2", 15000), ("Design (hours)", "10", 6000)]),
                ("design 10 hours at 60 EUR", [("Design (hours)", "10", 6000)]),
                ("design: 10 hours at 60 EUR", [("Design (hours)", "10", 6000)]),
                ("1,000 stickers at 0.10 EUR", [("Stickers", "1000", 10)]),
                ("10 hours of design at 60 an hour", [("Design (hours)", "10", 6000)]),
                ("3 x logo at 150 EUR", [("Logo", "3", 15000)]),
                ("3D model 300", [("3D model", "1", 30000)]),
                ("banner 300x250 120", [("Banner 300x250", "1", 12000)]),
                ("Website 2,000.50 EUR", [("Website", "1", 200050)]),
                ("Fee 1,234,567.89 EUR", [("Fee", "1", 123456789)])):
            self.assertEqual([(r["desc"], r["qty"], r["price"]) for r in Q.items_from(text)[0]], want, text)

    def test_unclear_lines_are_refused_never_guessed(self):
        for text in ("10 hours of design at 60 EUR (incl. 2 revisions)", "10 hours of design at 60 EUR with 20% discount",
                     "10 hours of design at 60 EUR by 15.12", "EUR 900 website", "design at 60 EUR and more",
                     "design 60 EUR x 10", "10 hours of design 60 EUR", "hosting 12 months 10 EUR", "Logo for 300",
                     "Phase 1 300", "logo 3 300", "logo 300 300", "logo 300 - 50", "logo 300 minus 50",
                     "logo 300 or 250", "logo 300 EUR 2", "3 x logo 1 500", "3 x logo 150 EUR 2", "3 x logo 150 2",
                     "3 x logo €150 2", "2 x design 60 EUR x 10", "3 x logo 150 x 2", "10 hours of design 60 EUR at 2", "logo €300 50", "Support 1 200 BGN", "Logo | 1 | 0.125",
                     "100 pcs of stickers at 0.125 EUR"):
            with self.assertRaises(ValueError, msg=text):
                Q.items_from(text)

    def test_leva_become_euro(self):
        for text in ("Support 1,200 BGN", "Support 1.200 BGN", "Support | 1 200 BGN"):
            self.assertEqual(Q.items_from(text), ([{"desc": "Support", "qty": "1", "price": 61355}], "EUR"), text)


class Flow(unittest.TestCase):
    def setUp(self):
        fresh()

    def test_needs_the_business_first(self):
        self.assertIn("first fill in your business details",
                      run("quote_create", {"client": "Acme Test", "items": "Design | 1 | 500"}))

    def test_quote_pdf_accept_invoice_and_deal(self):
        B.set_profile(name="Test Studio Ltd", vat_rate="20")
        B.new_invoice({"name": "Earlier Client"}, [{"desc": "Old work", "qty": "1", "price": 1000}], lang="en")
        d = D.add("Acme Test", "website", 500000, "EUR", "contacted")
        out = run("quote_create", {"client": "", "items": "10 hours of design at 60; Hosting | 1 | 120", "deal": d["id"]})
        self.assertTrue(out.startswith("quote Q-000001 for Acme Test: 864.00 EUR (net 720.00 EUR, VAT 20 %)"), out)
        from pypdf import PdfReader

        text = PdfReader(created(out)).pages[0].extract_text()
        for part in ("QUOTE", "Q-000001", "Valid until", "Test Studio Ltd", "Acme Test", "Design (hours)", "864.00"):
            self.assertIn(part, text)
        for part in ("INVOICE", "ORIGINAL", "Pay to"):
            self.assertNotIn(part, text)
        self.assertEqual(B.load()["next"], 2)  # a quote never uses an invoice number
        self.assertEqual((D.get(d["id"])["stage"], D.get(d["id"])["quote"]), ("proposal", "Q-000001"))
        run("quote_create", {"client": "Globex Test", "items": "Audit 300"})
        self.assertEqual([q["number"] for q in Q.load()["quotes"]], ["Q-000001", "Q-000002"])
        self.assertEqual(run("quote_status", {"quote": "Q-000001", "status": "sent"}), "quote Q-000001 is now sent")
        out = run("quote_accept", {"quote": "1"})
        self.assertTrue(out.startswith("quote Q-000001 accepted: invoice no. 0000000002 for Acme Test, 864.00 EUR"), out)
        inv = B.find_invoice("0000000002")
        q = Q.get("Q-000001")
        self.assertEqual(inv["items"], q["items"])
        self.assertEqual((inv["vat_rate"], inv["currency"]), ("20", "EUR"))
        self.assertIn("Quote Q-000001", inv["notes"])
        self.assertEqual((q["status"], q["invoice"]), ("accepted", "0000000002"))
        dd = D.get(d["id"])
        self.assertEqual((dd["stage"], dd["invoice"], dd["quote"]), ("won", "0000000002", "Q-000001"))
        self.assertEqual(B.load()["next"], 3)
        self.assertIn("already accepted", run("quote_accept", {"quote": "Q-000001"}))
        self.assertIn("accepted and invoiced", run("quote_status", {"quote": "Q-000001", "status": "draft"}))
        self.assertIn("it stays", run("quote_delete", {"quote": "Q-000001"}))

    def test_refusals_happen_before_an_invoice_number_is_used(self):
        B.set_profile(name="Test Studio Ltd")
        d = D.add("Acme Test", "site", 100000, "EUR", "won")
        D.update(d["id"], invoice="0000000009")
        run("quote_create", {"client": "Acme Test", "items": "Site 1000", "deal": d["id"]})
        self.assertIn("already has invoice no. 0000000009", run("quote_accept", {"quote": "Q-000001"}))
        run("quote_create", {"client": "Beta Test", "items": "Logo 200"})
        run("quote_status", {"quote": "Q-000002", "status": "declined"})
        self.assertIn("was declined", run("quote_accept", {"quote": "Q-000002"}))
        self.assertEqual((B.load()["next"], B.load()["invoices"]), (1, []))

    def test_states_expiry_and_reminders(self):
        B.set_profile(name="Test Studio Ltd")
        q = Q.new_quote({"name": "Acme Test"}, [{"desc": "Design", "qty": "1", "price": 50000}], valid_days=10,
                        issued=TODAY - timedelta(days=8))
        self.assertEqual(Q.status_of(q), "draft")
        self.assertEqual(Q.status_of(q, TODAY + timedelta(days=3)), "expired")
        with self.assertRaises(ValueError):
            Q.set_status(q["id"], "accepted")  # only accept makes it accepted (with the invoice)
        Q.set_status(q["id"], "sent")
        noon = datetime.combine(TODAY, datetime.min.time()).replace(hour=12)
        self.assertEqual(len(Q.fire_due(noon)), 1)  # valid until the day after tomorrow
        self.assertIn("valid until", caught[-1][1])
        self.assertEqual(Q.fire_due(noon), [])  # once
        self.assertEqual(Q.fire_due(noon.replace(hour=23)), [])  # never at night
        later = noon + timedelta(days=5)
        self.assertIn("expired", Q.fire_due(later)[0])
        self.assertEqual(Q.fire_due(later + timedelta(days=1)), [])
        Q.set_status(q["id"], "declined")
        self.assertEqual(Q.status_of(Q.get(q["id"]), TODAY + timedelta(days=30)), "declined")

    def test_currency_said_twice_must_agree(self):
        B.set_profile(name="Test Studio Ltd")
        self.assertIn("the lines are in EUR, not USD", run("quote_create", {"client": "Acme Test", "items": "Support 100 BGN",
                                                                            "currency": "USD"}))
        self.assertIn("VAT must be a number", run("quote_create", {"client": "Acme Test", "items": "Design 100", "vat_rate": "abc"}))
        self.assertIn("VAT must be between", run("quote_create", {"client": "Acme Test", "items": "Design 100", "vat_rate": "nan"}))

    def test_a_whole_client_name_wins_over_a_shared_word(self):
        B.set_profile(name="Test Studio Ltd")
        run("quote_create", {"client": "Acme Test", "items": "Design 100"})
        run("quote_accept", {"quote": "Q-000001"})
        run("quote_create", {"client": "Acme Corp", "items": "Website 9999"})
        self.assertEqual(Q.find("Acme Test")["number"], "Q-000001")  # never Acme Corp's open quote
        self.assertEqual(Q.find("Acme Corp")["number"], "Q-000002")
        self.assertEqual(Q.match("acme corporation"), Q.match("acme"))  # not a whole name: by word, both clients
        self.assertIn("VAT must be between", run("quote_create", {"client": "Acme Test", "items": "Design 100",
                                                                  "vat_rate": "20.000001"}))

    def test_a_half_done_accept_is_finished_never_repeated(self):
        B.set_profile(name="Test Studio Ltd")
        run("quote_create", {"client": "Acme Test", "items": "Design 100"})
        real = Q.mark_accepted
        Q.mark_accepted = lambda *a, **k: (_ for _ in ()).throw(OSError("disk busy"))
        try:
            out = run("quote_accept", {"quote": "Q-000001"})
        finally:
            Q.mark_accepted = real
        self.assertIn("invoice no. 0000000001 was made", out)
        self.assertIn("already made from this quote", run("quote_accept", {"quote": "Q-000001"}))
        self.assertEqual([i["number"] for i in B.load()["invoices"]], ["0000000001"])
        self.assertEqual(Q.get("Q-000001")["invoice"], "0000000001")

    def test_a_failed_invoice_pdf_is_made_on_the_second_try(self):
        B.set_profile(name="Test Studio Ltd")
        run("quote_create", {"client": "Acme Test", "items": "Design 100"})
        real = B.invoice_pdf
        B.invoice_pdf = lambda *a, **k: (_ for _ in ()).throw(OSError("no fonts"))
        try:
            self.assertIn("ERROR", run("quote_accept", {"quote": "Q-000001"}))
        finally:
            B.invoice_pdf = real
        out = run("quote_accept", {"quote": "Q-000001"})
        self.assertIn("Invoice 0000000001", out)
        self.assertEqual(len(B.load()["invoices"]), 1)
        self.assertTrue(os.path.isfile(B.find_invoice("0000000001")["file"]))

    def test_parallel_accepts_make_one_invoice(self):
        B.set_profile(name="Test Studio Ltd")
        run("quote_create", {"client": "Acme Test", "items": "Design 100"})
        outs = []
        threads = [threading.Thread(target=lambda: outs.append(run("quote_accept", {"quote": "Q-000001"}))) for _ in range(3)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(len(B.load()["invoices"]), 1)
        self.assertEqual(sum("accepted: invoice" in o for o in outs), 1)

    def test_the_card_after_a_half_done_accept_names_the_invoice_already_made(self):
        from vaelon.tools.money import _accept_card

        B.set_profile(name="Test Studio Ltd")
        run("quote_create", {"client": "Acme Test", "items": "Design 100"})
        real = Q.mark_accepted
        Q.mark_accepted = lambda *a, **k: (_ for _ in ()).throw(OSError("disk busy"))
        try:
            run("quote_accept", {"quote": "Q-000001"})
        finally:
            Q.mark_accepted = real
        self.assertIn("links invoice no. 0000000001", _accept_card({"quote": "Q-000001"}))

    def test_the_card_names_the_quote_and_several_matches_ask(self):
        from vaelon.tools.money import _accept_card

        B.set_profile(name="Test Studio Ltd")
        run("quote_create", {"client": "Acme Test", "items": "Design 120"})
        run("quote_create", {"client": "Acme Test", "items": "Website 10,800"})
        self.assertIn("several quotes match: Q-000002, Q-000001", run("quote_accept", {"quote": "Acme"}))
        card = _accept_card({"quote": "Q-000002"}).replace(" ", " ")
        for part in ("Q-000002", "Acme Test", "10,800.00 EUR", "1 line", "INVOICE no. 0000000001"):
            self.assertIn(part, card)
        run("quote_status", {"quote": "Q-000002", "status": "declined"})
        self.assertIn("quote Q-000001 accepted", run("quote_accept", {"quote": "Acme"}))  # one open quote left

    def test_undo_keeps_the_deal_won_with_its_invoice(self):
        B.set_profile(name="Test Studio Ltd")
        d = D.add("Acme Test", "site", 100000, "EUR", "lead")
        run("quote_create", {"client": "", "items": "Site 1000", "deal": d["id"]})
        run("quote_accept", {"quote": "Q-000001"})
        for _ in range(6):
            undo.undo()
        dd = D.get(d["id"])
        self.assertEqual((dd["stage"], dd["invoice"], dd["quote"]), ("won", "0000000001", "Q-000001"))
        self.assertEqual(Q.get("Q-000001")["status"], "accepted")

    def test_bulgarian_pdf_labels(self):
        B.set_profile(name="Test Studio Ltd", bank="Bank: test only")
        out = run("quote_create", {"client": "Acme Test", "items": "Design 100", "language": "bg"})
        from pypdf import PdfReader

        text = PdfReader(created(out)).pages[0].extract_text()
        self.assertIn("ОФЕРТА", text)  # the title, in the quote's own language
        self.assertNotIn("test only", text)  # no bank line on a quote

    def test_undo_never_gives_a_number_twice(self):
        B.set_profile(name="Test Studio Ltd")
        run("quote_create", {"client": "Acme Test", "items": "Design 100"})
        undo.undo()  # the PDF goes
        undo.undo()  # the quote goes
        self.assertEqual(Q.load()["quotes"], [])
        run("quote_create", {"client": "Acme Test", "items": "Design 100"})
        self.assertEqual(Q.load()["quotes"][0]["number"], "Q-000002")

    def test_undo_keeps_an_accepted_quote(self):
        B.set_profile(name="Test Studio Ltd")
        run("quote_create", {"client": "Acme Test", "items": "Design 100"})
        before = Q.snapshot()
        run("quote_accept", {"quote": "Q-000001"})
        Q.restore_all(before)
        self.assertEqual(Q.get("Q-000001")["status"], "accepted")


class Words(unittest.TestCase):
    def setUp(self):
        fresh()
        B.set_profile(name="Test Studio Ltd")

    def test_list_and_make(self):
        self.assertIn("No quotes yet", ask("what quotes do I have?").answer)
        hit = ask("make a quote for Globex Test: 3 days of consulting at 400 EUR")
        self.assertEqual((hit.tool, hit.args), ("quote_create", {"client": "Globex Test", "items": "3 days of consulting at 400 EUR"}))
        run(hit.tool, hit.args)
        self.assertIn("Q-000001 Globex Test: 1,200.00 EUR - draft", ask("show my quotes").answer.replace(" ", " "))
        self.assertIsNone(ask("can you make a quote for Acme: design 100 EUR?"))  # a question: the model answers
        self.assertIsNone(ask("make a quote for Acme: something nice"))  # lines it cannot read
        self.assertIsNone(ask("give me a quote about courage"))
        for text in ("quotes", "show me quotes", "quotes about life"):
            hit = ask(text)
            self.assertFalse(hit and hit.answer and "quote" in hit.answer.lower() and "Q-0" in hit.answer, text)
        self.assertIn("Q-000001", ask("my open quotes").answer)
        self.assertIn("money", router.groups_for("make a quote for Acme"))

    def test_tool_rules(self):
        self.assertEqual(registry.REGISTRY["quote_accept"].risk, Risk.DANGEROUS)  # always asks: it issues an invoice
        self.assertIn("quotes_list", registry.PRIVATE_TOOLS)


class Roles(unittest.TestCase):
    def setUp(self):
        fresh()
        company.enable("Owner One", "1234")
        self.acme = company.add_workspace("Acme Ltd")
        company.switch(self.acme["id"])
        B.set_profile(name="Acme Ltd")
        for name, role, pin in (("Sam Sales", "sales", "3333"), ("Vic Viewer", "viewer", "4444"),
                                ("Mo Member", "member", "5555"), ("Ann Accountant", "accountant", "2222")):
            company.add_user(name, role, pin, [self.acme["id"]])

    def tearDown(self):
        fresh()

    def as_(self, name, pin):
        company.sign_in(next(u["id"] for u in company.users() if u["name"] == name), pin)

    def test_who_may_do_what(self):
        self.as_("Sam Sales", "3333")
        self.assertTrue(run("quote_create", {"client": "Client Test", "items": "Design 100"}).startswith("quote Q-000001"))
        self.assertIn("ERROR", run("quote_accept", {"quote": "Q-000001"}))  # sales may not issue invoices
        self.assertEqual(B.load()["invoices"], [])
        self.as_("Vic Viewer", "4444")
        self.assertIn("Q-000001", run("quotes_list", {}))
        self.assertIn("ERROR", run("quote_status", {"quote": "Q-000001", "status": "sent"}))
        self.as_("Mo Member", "5555")
        self.assertIn("ERROR", run("quotes_list", {}))
        self.as_("Ann Accountant", "2222")
        from vaelon import quotes_api

        self.assertTrue(quotes_api.overview()["quotes"][0]["may_accept"])
        self.as_("Sam Sales", "3333")
        d = D.add("Deal Client", "site", 100000)
        run("quote_create", {"client": "", "items": "Site 1000", "deal": d["id"]})
        self.as_("Ann Accountant", "2222")
        rows = {q["number"]: q["may_accept"] for q in quotes_api.overview()["quotes"]}
        self.assertEqual(rows, {"Q-000001": True, "Q-000002": False})  # no deals.write: that one is not hers to accept
        self.assertIn("invoice no. 0000000001", run("quote_accept", {"quote": "Q-000001"}))
        actions = [e.get("action", "") for e in journal.read()]
        self.assertIn("quote made", actions)
        self.assertIn("quote accepted", actions)


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
        self.assertEqual(self.call("GET", "/quotes", token=False)[0], 401)
        self.assertEqual(self.call("POST", "/quotes", {"action": "add"}, origin="https://evil.example")[0], 403)
        o = self.call("GET", "/quotes")[1]
        self.assertEqual((o["quotes"], o["next"], o["has_business"]), ([], "Q-000001", False))
        B.set_profile(name="Test Studio Ltd")
        d = D.add("Acme Test", "site", 100000, "EUR", "lead")
        code, r = self.call("POST", "/quotes", {"action": "add", "client": {"name": ""}, "deal": d["id"], "valid_days": 14,
                                                "items": [{"desc": "Site", "qty": "1", "price": "1000"}]})
        self.assertEqual(code, 200, r)
        self.assertTrue(r["path"].endswith(".pdf") and os.path.isfile(r["path"]))
        qid = r["quote"]["id"]
        o = self.call("GET", "/quotes")[1]
        self.assertEqual((o["quotes"][0]["client"], o["quotes"][0]["deal_label"], o["open"]), ("Acme Test", "Acme Test - site",
                                                                                              {"EUR": 100000}))  # no VAT set
        self.assertEqual(self.call("POST", "/quotes", {"action": "status", "id": qid, "status": "sent"})[0], 200)
        self.assertEqual(self.call("POST", "/quotes", {"action": "status", "id": qid, "status": "accepted"})[0], 400)
        code, r = self.call("POST", "/quotes", {"action": "accept", "id": qid})
        self.assertEqual((code, r["number"]), (200, "0000000001"))
        self.assertTrue(r["path"].endswith(".pdf"))
        self.assertEqual(self.call("POST", "/quotes", {"action": "delete", "id": qid})[0], 400)  # accepted stays
        self.assertEqual(self.call("POST", "/quotes", {"action": "delete", "id": "nope"})[0], 400)
        code, r = self.call("POST", "/quotes", {"action": "add", "client": {"name": "Beta Test"},
                                                "items": [{"desc": "Website v2; 5 pages", "qty": "1", "price": "900"}]})
        self.assertEqual(code, 200, r)
        q = Q.get(r["quote"]["id"])
        self.assertEqual(q["items"], [{"desc": "Website v2; 5 pages", "qty": "1", "price": 90000}])  # never split
        code, r = self.call("POST", "/quotes", {"action": "add", "client": {"name": "Beta Test"},
                                                "items": [{"desc": "Logo", "qty": "1", "price": "1O0"}]})
        self.assertEqual(code, 400)  # a typo is refused, never read as 10
        self.assertIn("must be a number", r["error"])
        code, r = self.call("POST", "/quotes", {"action": "add", "client": {"name": "Beta Test"},
                                                "items": [{"desc": "Stickers", "qty": "100", "price": "0.125"}]})
        self.assertEqual((code, "at most two decimals" in r["error"]), (400, True))  # never quietly 0.13


if __name__ == "__main__":
    unittest.main()
