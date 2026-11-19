"""Demo data: loads once, everything is marked, removing it leaves the owner's own entries and the real invoice
numbering exactly as they were. Offline, a temporary data folder."""
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

os.environ["VAELON_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vaelon import agenda as A, bills as B, budget as BU, config, deals as D, demo, intents  # noqa: E402


class Demo(unittest.TestCase):
    def test_load_and_remove_only_the_demo(self):
        own_bill = B.add_bill("My landlord", 50000, "EUR", date.today() + timedelta(days=5))
        B.set_profile(name="My Own Ltd", vat_rate="0")
        own_inv = B.new_invoice({"name": "Real client"}, B.parse_items("Work | 1 | 100"))
        own_entry = BU.add("expense", 1000, "EUR", "", "my lunch")
        BU.set_limit("groceries", 30000)
        own_deal = D.add("My client", "real deal", 10000)
        own_ev = A.add("My dentist", A.parse_iso("2030-01-02T10:00"))
        before_next = B.load()["next"]

        out = demo.load()
        self.assertTrue(Path(out["backup"]).is_dir() and (Path(out["backup"]) / B.FILE).exists())
        self.assertTrue(demo.present())
        data = B.load()
        self.assertEqual(data["me"]["name"], "My Own Ltd")  # own business details are never replaced
        self.assertEqual(data["next"], before_next)  # demo invoices do not use the real series
        self.assertEqual(sorted(i["number"] for i in data["invoices"] if i.get("demo")), ["DEMO-000001", "DEMO-000002"])
        self.assertEqual(BU.load()["limits"]["groceries"], 30000)  # an own limit stays
        self.assertGreaterEqual(len(D.load()), 5)
        self.assertTrue(any(e.get("demo") for e in A.load()))
        with self.assertRaises(ValueError):
            demo.load()  # only once

        counts = demo.remove()
        self.assertEqual((counts["bills"] >= 5, counts["invoices"], counts["deals"], counts["events"]), (True, 2, 4, 3))
        data = B.load()
        self.assertEqual([b["id"] for b in data["bills"]], [own_bill["id"]])
        self.assertEqual([i["id"] for i in data["invoices"]], [own_inv["id"]])
        self.assertEqual(data["me"]["name"], "My Own Ltd")
        self.assertEqual([e["id"] for e in BU.load()["entries"]], [own_entry["id"]])
        self.assertEqual(BU.load()["limits"], {"groceries": 30000})
        self.assertEqual([d["id"] for d in D.load()], [own_deal["id"]])
        self.assertEqual([e["id"] for e in A.load()], [own_ev["id"]])
        self.assertFalse(demo.present())

    def test_by_voice(self):
        for f in (B.FILE, BU.FILE, D.FILE, A.FILE):
            (config.HOME / f).unlink(missing_ok=True)
        self.assertTrue(intents.detect("зареди демо данни").answer.startswith("Заредих демо данни"))
        self.assertIn("already", intents.detect("load demo data").answer)
        self.assertTrue(intents.detect("махни демо данните").answer.startswith("Махнах демо данните"))
        self.assertTrue(B.load()["me"] == {})  # the demo business details went too (none of the owner's were set)
        hit = intents.detect("what is a demo")
        self.assertTrue(hit is None or hit.tool == "wiki")  # a question about demos does not touch the data
        self.assertFalse(demo.present())


if __name__ == "__main__":
    unittest.main()
