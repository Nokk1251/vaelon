"""Company mode: off by default; companies keep their own money data; roles allow exactly what they say; a locked
app answers only the sign-in; people who are not the owner never reach the owner's memory, conversations, calendar
or settings and see only their own tasks; the journal records who did what and notices tampering; reminders cover
every company; connected tools (MCP) only for owner / accountant. Offline, temporary data folder, made-up people."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

os.environ["VAELON_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vaelon import bills as B, budget as BU, company, config, deals as D, intents, journal, reminders, server  # noqa: E402
from vaelon.config import Config  # noqa: E402
from vaelon.tools import registry  # noqa: E402

registry.load_builtin()
T = date.today()
caught = []
reminders.notify = lambda title, text, kind="reminder", toast=True: caught.append(text) or {}


def reset():
    import shutil

    for name in (B.FILE, BU.FILE, D.FILE, company.FILE, journal.FILE, "calendar.enc"):
        (config.HOME / name).unlink(missing_ok=True)
    shutil.rmtree(config.HOME / "workspaces", ignore_errors=True)
    company._session.update({"user": None, "workspace": company.PERSONAL})
    company._fails.clear()
    company.system(False)


def ask(text):
    hit = intents.detect(text)
    return hit.answer if hit else None


class Off(unittest.TestCase):
    def setUp(self):
        reset()

    def test_off_by_default_everything_as_before(self):
        self.assertFalse(company.enabled())
        self.assertTrue(company.can("users.manage"))
        B.add_bill("Rent", 40000, "EUR", T)
        self.assertEqual(company.data_dir(), config.HOME)
        self.assertTrue((config.HOME / B.FILE).exists())
        self.assertEqual(journal.read(), [])  # nothing journaled while off


class Mode(unittest.TestCase):
    def setUp(self):
        reset()
        self.owner = company.enable("Owner One", "1234")
        self.acme = company.add_workspace("Acme Ltd")
        self.beta = company.add_workspace("Beta Ltd")

    def as_(self, name, pin):
        uid = next(u["id"] for u in company.users() if u["name"] == name)
        company.sign_in(uid, pin)

    def test_companies_keep_their_own_money(self):
        B.add_bill("Personal rent", 50000, "EUR", T)
        company.switch(self.acme["id"])
        self.assertEqual(B.load()["bills"], [])
        B.add_bill("Acme supplier", 12000, "EUR", T)
        self.assertTrue((config.HOME / "workspaces" / self.acme["id"] / B.FILE).exists())
        company.switch(company.PERSONAL)
        self.assertEqual([b["vendor"] for b in B.load()["bills"]], ["Personal rent"])

    def test_roles(self):
        company.add_user("Ann Accountant", "accountant", "2222", [self.acme["id"]])
        company.add_user("Sam Sales", "sales", "3333", [self.acme["id"]])
        company.add_user("Vic Viewer", "viewer", "4444", [self.acme["id"], self.beta["id"]])
        self.as_("Ann Accountant", "2222")
        self.assertEqual(company.workspace(), self.acme["id"])  # never the owner's personal workspace
        with self.assertRaises(company.Denied):
            company.switch(company.PERSONAL)
        with self.assertRaises(company.Denied):
            company.switch(self.beta["id"])  # not given to her
        B.add_bill("Acme power", 6000, "EUR", T + timedelta(days=3))
        with self.assertRaises(company.Denied):
            company.add_user("X", "member", "5555", [self.acme["id"]])
        with self.assertRaises(company.Denied):
            D.add("Client")  # accountants read deals only
        self.as_("Sam Sales", "3333")
        D.add("Client", "site", 100000)
        with self.assertRaises(company.Denied):
            B.add_bill("Nope", 100, "EUR", T)
        self.assertTrue(ask("какви сметки имам?").startswith("Не мога"))
        self.assertIn("Open deals: 1", ask("how are my deals going?"))
        self.as_("Vic Viewer", "4444")
        for write in (lambda: B.add_bill("x", 1, "EUR", T), lambda: BU.add("expense", 100), lambda: D.add("y")):
            with self.assertRaises(company.Denied):
                write()
        self.assertIn("Unpaid bills (1)", ask("what bills do I have to pay?"))

    def test_pins_and_lockout(self):
        company.add_user("Ann Accountant", "accountant", "2222", [self.acme["id"]])
        uid = next(u["id"] for u in company.users() if u["name"] == "Ann Accountant")
        for _ in range(5):
            with self.assertRaises(company.Denied):
                company.sign_in(uid, "0000")
        with self.assertRaisesRegex(company.Denied, "too many"):
            company.sign_in(uid, "2222")  # locked for a minute even with the right PIN
        with self.assertRaises(ValueError):
            company.add_user("Short", "member", "12", [self.acme["id"]])
        raw = (config.HOME / company.FILE).read_text("utf-8")
        self.assertNotIn("2222", raw)
        self.assertNotIn("Ann", raw)  # the whole file is sealed

    def test_journal_records_and_notices_tampering(self):
        company.switch(self.acme["id"])
        B.add_bill("Acme power", 6000, "EUR", T)
        BU.add("expense", 1500, "EUR", note="Lidl")
        entries = journal.read()
        self.assertEqual([e["action"] for e in entries], ["budget entry added", "bill added"])
        self.assertEqual(entries[0]["who"], "Owner One")
        self.assertIn("Acme power", entries[1]["detail"])
        self.assertIn("opened", [e["action"] for e in journal.read(ws_dir=config.HOME)])  # admin events: one journal
        B.add_bill("Acme water", 1800, "EUR", T)
        self.assertEqual(journal.verify(), (True, "3 entries, chain intact"))
        p = company.data_dir() / journal.FILE
        lines = p.read_text("utf-8").splitlines()
        p.write_text("\n".join([lines[0], lines[2]]) + "\n", "utf-8")  # a line removed outside Vaelon
        ok, what = journal.verify()
        self.assertFalse(ok)
        self.assertIn("line 2", what)

    def test_reminders_cover_every_company(self):
        company.switch(self.acme["id"])
        B.add_bill("Acme rent", 90000, "EUR", T + timedelta(days=1), remind=3)
        company.switch(company.PERSONAL)
        caught.clear()
        company.system(True)
        try:
            for d in company.all_dirs():
                with company.use_dir(d):
                    B.fire_due(datetime.combine(T, datetime.min.time()).replace(hour=10))
        finally:
            company.system(False)
        self.assertTrue(any("Acme rent" in c for c in caught), caught)

    def test_mcp_only_for_owner_and_accountant(self):
        @registry.tool("mcp_books_list", "test tool", {}, group="mcp")
        def _t(ctx):
            return "listed"

        company.add_user("Sam Sales", "sales", "3333", [self.acme["id"]])
        self.as_("Sam Sales", "3333")
        out = registry.execute(registry.Ctx(Config(), approver=lambda r: True), "mcp_books_list", {})
        self.assertTrue(out.startswith("DENIED"), out)
        del registry.REGISTRY["mcp_books_list"]

    def test_turning_off_needs_the_owner_pin(self):
        with self.assertRaises(company.Denied):
            company.disable("9999")
        company.disable("1234")
        self.assertFalse(company.enabled())
        self.assertEqual(company.workspace(), company.PERSONAL)

    def test_work_mode_never_sees_the_owners_memory(self):
        from vaelon.agent import Agent

        a = Agent(Config(provider="mock"), load_extensions=False)
        a.memory.add("the owner's secret: blue door")
        twin = a.fork().work_mode([])
        self.assertEqual(twin.memory.search("secret"), [])
        self.assertEqual(twin.history, [])
        self.assertNotIn("fs_read", twin.only_tools)
        self.assertNotIn("remember", twin.only_tools)
        self.assertIn("bill_add", twin.only_tools)
        self.assertTrue(a.memory.search("secret"))  # the owner's agent still has it


class Api(unittest.TestCase):
    def setUp(self):
        reset()
        self.token = server.get_token()
        self.srv = server.serve(Config(provider="mock"), port=0)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def call(self, method, path, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None)
        req.add_header("Authorization", f"Bearer {self.token}")
        try:
            return 200, json.load(urllib.request.urlopen(req, timeout=20))
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            return e.code, json.loads(raw) if raw.startswith("{") else {}

    def test_locked_app_and_personal_parts(self):
        code, r = self.call("POST", "/company", {"action": "enable", "name": "Owner One", "pin": "1234"})
        self.assertEqual(code, 200)
        acme = self.call("POST", "/company", {"action": "add_workspace", "name": "Acme Ltd"})[1]["workspace"]
        r = self.call("POST", "/company", {"action": "add_user", "name": "Mia Member", "role": "member", "pin": "5555",
                                           "workspaces": [acme["id"]]})[1]
        mia = r["user"]["id"]
        self.assertEqual(self.call("POST", "/company", {"action": "sign_out"})[0], 200)
        for path in ("/bills", "/budget", "/catalog", "/chats", "/jobs"):
            self.assertEqual(self.call("GET", path)[0], 423, path)
        self.assertEqual(self.call("POST", "/chat", {"text": "hi"})[0], 423)
        s = self.call("GET", "/company")[1]
        self.assertTrue(s["locked"])
        self.assertEqual({p["name"] for p in s["people"]}, {"Owner One", "Mia Member"})
        self.assertEqual(self.call("POST", "/company", {"action": "sign_in", "user": mia, "pin": "0000"})[0], 403)
        code, r = self.call("POST", "/company", {"action": "sign_in", "user": mia, "pin": "5555"})
        self.assertEqual((code, r["state"]["workspace"]["name"]), (200, "Acme Ltd"))
        for path in ("/chats", "/calendar", "/settings", "/notices", "/models/local", "/ollama/pull", "/update"):
            self.assertEqual(self.call("GET", path)[0], 403, path)
        self.assertEqual(self.call("POST", "/ollama/pull", {"model": "gemma3:4b"})[0], 403)  # the owner's choice only
        self.assertEqual(self.call("GET", "/catalog")[1]["memory"]["recent"], [])
        code, r = self.call("POST", "/budget", {"action": "add", "kind": "expense", "amount": "12", "note": "Lidl"})
        self.assertEqual(code, 200)
        self.assertEqual(self.call("POST", "/bills", {"action": "add", "vendor": "x", "amount": "5"})[0], 403)  # member: no bills
        self.assertEqual(self.call("POST", "/company", {"action": "add_workspace", "name": "Mine"})[0], 403)
        self.assertEqual(self.call("GET", "/journal")[0], 403)
        # the owner signs back in and sees the member's expense in the journal
        owner = next(p["id"] for p in self.call("GET", "/company")[1]["people"] if p["name"] == "Owner One")
        self.call("POST", "/company", {"action": "sign_out"})
        self.call("POST", "/company", {"action": "sign_in", "user": owner, "pin": "1234"})
        self.call("POST", "/company", {"action": "switch", "id": acme["id"]})
        j = self.call("GET", "/journal")[1]
        self.assertTrue(j["intact"])
        self.assertTrue(any(e["who"] == "Mia Member" and e["action"] == "budget entry added" for e in j["entries"]))


if __name__ == "__main__":
    unittest.main()
