"""The findings of the code review of company mode (2026-11-15), each kept fixed by a test. Offline, temporary
data folder, made-up people and files."""
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

os.environ["VAELON_HOME"] = tempfile.mkdtemp()
OUT = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vaelon import bills as B, company, config, deals as D, journal, server  # noqa: E402
from vaelon.config import Config  # noqa: E402
from vaelon.security import undo  # noqa: E402
from vaelon.tools import registry  # noqa: E402
from vaelon.tools.create import out_dir  # noqa: E402

registry.load_builtin()
T = date.today()


def reset():
    import shutil

    for name in (B.FILE, "budget.enc", D.FILE, company.FILE, journal.FILE, "calendar.enc"):
        (config.HOME / name).unlink(missing_ok=True)
    shutil.rmtree(config.HOME / "workspaces", ignore_errors=True)
    company._session.update({"user": None, "workspace": company.PERSONAL})
    company.unbind()
    undo._stack.clear()


class Review(unittest.TestCase):
    def setUp(self):
        reset()
        company.enable("Owner One", "1234")
        self.acme = company.add_workspace("Acme Ltd")
        self.beta = company.add_workspace("Beta Ltd")

    def as_(self, name, pin):
        company.sign_in(next(u["id"] for u in company.users() if u["name"] == name), pin)

    def test_work_mode_reads_only_the_company_folder(self):  # CRITICAL-1, CRITICAL-2
        from vaelon.agent import Agent

        company.add_user("Mia Member", "member", "5555", [self.acme["id"]])
        self.as_("Mia Member", "5555")
        a = Agent(Config(provider="mock", output_dir=OUT, allowed_roots=[str(Path.home())]), load_extensions=False)
        twin = a.fork().work_mode([])
        self.assertEqual(twin.cfg.allowed_roots, [str(out_dir(twin.cfg))])
        self.assertIn("Companies", twin.cfg.allowed_roots[0])
        for name in ("read_document", "look_at_image", "delegate", "fs_read", "remember"):
            self.assertNotIn(name, twin.only_tools, name)
        secret = Path(OUT) / "owner-secret.txt"
        secret.write_text("the owner's private note", "utf-8")
        c = registry.Ctx(twin.cfg, allowed_tools=twin.only_tools, approver=lambda r: True)
        self.assertTrue(registry.execute(c, "read_document", {"path": str(secret)}).startswith("ERROR"))
        self.assertIn("BLOCKED", registry.execute(c, "bill_from_file", {"path": str(secret)}))
        self.assertTrue(a.cfg.allowed_roots == [str(Path.home())])  # the owner's own agent is unchanged

    def test_undo_stays_in_its_company_and_with_its_person(self):  # CRITICAL-3, HIGH-1
        company.switch(self.beta["id"])
        B.add_bill("Beta landlord", 50000, "EUR", T)
        company.switch(self.acme["id"])
        before = B.snapshot()
        B.add_bill("Acme supplier", 12000, "EUR", T)
        undo.push("add bill Acme supplier", lambda: B.restore_all(before))
        company.switch(self.beta["id"])
        self.assertEqual(undo.undo(), "Nothing to undo.")  # not in this company
        self.assertEqual([b["vendor"] for b in B.load()["bills"]], ["Beta landlord"])
        company.add_user("Ann Accountant", "accountant", "2222", [self.acme["id"]])
        self.as_("Ann Accountant", "2222")
        self.assertEqual(undo.undo(), "Nothing to undo.")  # the owner's action is not hers to take back
        owner = next(u["id"] for u in company.users() if u["name"] == "Owner One")
        company.sign_in(owner, "1234")
        company.switch(self.acme["id"])
        self.assertTrue(undo.undo().startswith("Undone"))
        self.assertEqual(B.load()["bills"], [])
        company.switch(self.beta["id"])
        self.assertEqual([b["vendor"] for b in B.load()["bills"]], ["Beta landlord"])

    def test_a_locked_app_runs_nothing(self):  # HIGH-2
        company.sign_out()
        svc = server.Service(Config(provider="mock"))
        with self.assertRaises(company.Denied):
            svc.start("what do you know about me?")

    def test_pin_guessing_is_slowed_everywhere(self):  # HIGH-3
        for _ in range(5):
            with self.assertRaises(company.Denied):
                company.disable("0000")
        with self.assertRaisesRegex(company.Denied, "too many"):
            company.disable("1234")
        self.assertTrue(company.enabled())
        self.assertEqual(company.load()["fails"][next(u["id"] for u in company.users())][0], 5)  # kept in the file

    def test_files_of_one_company_are_not_reachable_from_another(self):  # HIGH-4
        cfg = Config(output_dir=OUT)
        company.switch(self.acme["id"])
        acme_folder = out_dir(cfg)
        acme_folder.mkdir(parents=True, exist_ok=True)
        inv = acme_folder / "Invoice 0000000001 Client.pdf"
        inv.write_bytes(b"%PDF-1.4 test")
        mine = Path(OUT) / "Vaelon money 2026.xlsx"
        mine.write_bytes(b"x")
        company.add_user("Bea Beta", "accountant", "7777", [self.beta["id"]])
        self.as_("Bea Beta", "7777")
        launched = []
        self.assertFalse(server.open_created(cfg, str(inv), launch=lambda p, r: launched.append(p))[0])
        self.assertFalse(server.open_created(cfg, str(mine), launch=lambda p, r: launched.append(p))[0])
        self.assertEqual(launched, [])

    def test_deal_invoice_checks_rights_first(self):  # MEDIUM-2
        company.switch(self.acme["id"])
        B.set_profile(name="Acme Ltd", vat_rate="0")
        d = D.add("Client", "site", 100000, "EUR", "won")
        company.add_user("Ann Accountant", "accountant", "2222", [self.acme["id"]])
        self.as_("Ann Accountant", "2222")
        c = registry.Ctx(Config(output_dir=OUT, allowed_roots=[OUT]), approver=lambda r: True)
        out = registry.execute(c, "deal_invoice", {"deal": d["id"]})
        self.assertIn("Denied", out)
        self.assertEqual(B.load()["invoices"], [])  # no orphan invoice

    def test_the_journal_notices_a_cut_end_and_a_missing_file(self):  # MEDIUM-4
        company.switch(self.acme["id"])
        for n in range(4):
            B.add_bill(f"Bill {n}", 100 + n, "EUR", T)
        self.assertTrue(journal.verify()[0])
        p = company.data_dir() / journal.FILE
        lines = p.read_text("utf-8").splitlines()
        p.write_text("\n".join(lines[:-2]) + "\n", "utf-8")
        ok, what = journal.verify()
        self.assertEqual((ok, what), (False, "2 entries at the end are missing"))
        p.unlink()
        self.assertEqual(journal.verify(), (False, "the journal file is missing"))
        self.assertTrue(any(e["action"] == "company added" for e in journal.read(ws_dir=config.HOME)))  # admin events: one place

    def test_no_sign_in_while_a_task_runs(self):  # MEDIUM-1
        from vaelon import company_api

        class Busy:
            def open_jobs(self):
                return 1
        code, r = company_api.act(Busy(), {"action": "sign_in", "user": "x", "pin": "1234"})
        self.assertEqual(code, 409)

    def test_locking_is_never_blocked_by_a_hanging_task(self):  # found by the exe check
        from types import SimpleNamespace

        from vaelon import company_api

        running = SimpleNamespace(status="running", cancelled=False)
        stopped = SimpleNamespace(status="running", cancelled=True)  # stopped, but its model call still hangs
        owner = next(u["id"] for u in company.users() if u["name"] == "Owner One")
        svc = SimpleNamespace(jobs={"a": running}, open_jobs=lambda: 1)
        self.assertEqual(company_api.act(svc, {"action": "sign_out"})[0], 200)  # locking: always
        self.assertEqual(company_api.act(svc, {"action": "sign_in", "user": owner, "pin": "1234"})[0], 409)
        svc.jobs = {"a": stopped}
        self.assertEqual(company_api.act(svc, {"action": "sign_in", "user": owner, "pin": "1234"})[0], 200)

    def test_a_task_keeps_its_person_and_company(self):  # MEDIUM-1
        company.add_user("Mia Member", "member", "5555", [self.acme["id"]])
        mia = next(u["id"] for u in company.users() if u["name"] == "Mia Member")
        company.bind(mia, self.acme["id"])
        try:
            self.assertEqual((company.user()["name"], company.workspace()), ("Mia Member", self.acme["id"]))
            self.assertFalse(company.can("bills.write"))
        finally:
            company.unbind()
        self.assertEqual(company.user()["name"], "Owner One")


if __name__ == "__main__":
    unittest.main()
