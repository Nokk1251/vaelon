"""The calendar: dates in words, repeats, clashes, reminders, .ics both ways, the fast answers and the app's API.
Offline; reminders are caught before they reach Windows."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta

os.environ["VAELON_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vaelon import agenda as A, config, intents, reminders, server  # noqa: E402
from vaelon.config import Config  # noqa: E402
from vaelon.security import undo  # noqa: E402
from vaelon.tools import registry  # noqa: E402

registry.load_builtin()
OUT = tempfile.mkdtemp()  # created files go here (never inside the data folder, which file tools may not touch)
SUNDAY = time.mktime((2026, 11, 15, 14, 0, 0, 0, 0, -1))  # Sunday 15 November 2026, 14:00


def when(text, now=SUNDAY):
    ts, rest = reminders.parse_when(text, now)
    return (time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else None), rest


def ctx():
    return registry.Ctx(Config(allowed_roots=[OUT], output_dir=OUT), approver=lambda r: True)


def future(days=3, hour=10):
    d = datetime.now().replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(days=days)
    return d


class Words(unittest.TestCase):
    def test_days_dates_and_months_in_both_languages(self):
        cases = {"dentist on Friday at 10": ("2026-11-20 10:00", "dentist"), "среща в петък в 10": ("2026-11-20 10:00", "среща"),
                 "следващия понеделник в 9:30 стендъп": ("2026-11-16 09:30", "стендъп"),
                 "на 20.11 в 15:00 обяд": ("2026-11-20 15:00", "обяд"), "on 20.11 at 3pm lunch": ("2026-11-20 15:00", "lunch"),
                 "20 ноември в 18 рожден ден": ("2026-11-20 18:00", "рожден ден"), "November 20 at 6pm": ("2026-11-20 18:00", ""),
                 "на 3.2.2027 изпит": ("2027-02-03 09:00", "изпит"), "20 March at 9": ("2027-03-20 09:00", ""),
                 "on Sunday at 8": ("2026-11-22 08:00", ""), "meet at 7pm on Monday": ("2026-11-16 19:00", "meet")}
        for text, (expect, rest) in cases.items():
            self.assertEqual(when(text), (expect, rest), text)

    def test_ordinary_words_and_numbers_are_not_dates(self):
        for text in ("call Ivan", "pay 20.50 leva", "I sat and waited", "the sun is bright", "version 3.11 is out"):
            self.assertIsNone(when(text)[0], text)
        self.assertEqual(when("the sun rises at 6")[0], "2026-11-16 06:00")  # "at 6" is a time; "sun" is not Sunday

    def test_the_old_forms_still_work(self):
        self.assertEqual(when("in 20 minutes call mum"), ("2026-11-15 14:20", "call mum"))
        self.assertEqual(when("утре в 9 да платя тока"), ("2026-11-16 09:00", "да платя тока"))
        self.assertEqual(when("2026-12-24 18:00 Christmas"), ("2026-12-24 18:00", "Christmas"))


class Store(unittest.TestCase):
    def setUp(self):
        (config.HOME / A.FILE).unlink(missing_ok=True)

    def test_encrypted_repeats_skips_and_clashes(self):
        start = datetime(2026, 1, 31, 10, 0)
        monthly = A.add("Rent", start, 30, repeat="monthly")
        raw = (config.HOME / A.FILE).read_text("utf-8")
        self.assertNotIn("Rent", raw)  # what you do and when is personal: encrypted on disk
        occ = A.occurrences(monthly, datetime(2026, 1, 1), datetime(2026, 5, 1))
        self.assertEqual([d.strftime("%m-%d") for d in occ], ["01-31", "02-28", "03-31", "04-30"])  # 31st -> month's last day
        weekly = A.add("Gym", datetime(2026, 11, 2, 18, 0), 60, repeat="weekly")
        self.assertEqual(len(A.occurrences(weekly, datetime(2027, 11, 1), datetime(2027, 12, 1))), 5)  # 5 Mondays; far ahead: still fast
        A.update(weekly["id"], skip=["2026-11-16T18:00"])
        days = [d.day for d, _ in A.between(datetime(2026, 11, 9), datetime(2026, 11, 24)) if _["id"] == weekly["id"]]
        self.assertEqual(days, [9, 23])
        A.add("Dentist", datetime(2026, 11, 23, 18, 30), 30)
        self.assertEqual([e["title"] for _, e in A.clashes(datetime(2026, 11, 23, 18, 0), 60)], ["Gym", "Dentist"])
        self.assertEqual(A.clashes(datetime(2026, 11, 23, 19, 0), 60), [])
        A.add("Holiday", datetime(2026, 11, 23), all_day=True)
        self.assertEqual(A.clashes(datetime(2026, 11, 23, 12, 0), 60), [])  # an all-day event does not block a slot
        self.assertEqual(A.find("dent")[0][1]["title"], "Dentist")

    def test_reminders_fire_once_per_occurrence(self):
        caught = []
        real = reminders.notify
        reminders.notify = lambda title, text, kind="reminder", toast=True: caught.append(text)
        try:
            A.add("Standup", datetime(2026, 11, 16, 9, 30), 15, repeat="daily", remind=10, place="Office")
            self.assertEqual(A.fire_due(datetime(2026, 11, 16, 9, 15)), [])  # too early
            self.assertEqual(A.fire_due(datetime(2026, 11, 16, 9, 21)), ["Standup at 09:30 - Office"])
            self.assertEqual(A.fire_due(datetime(2026, 11, 16, 9, 25)), [])  # not twice
            self.assertEqual(A.fire_due(datetime(2026, 11, 17, 9, 20)), ["Standup at 09:30 - Office"])  # the next day again
            A.add("Quiet", datetime(2026, 11, 16, 9, 30), remind=None)
            self.assertEqual(A.fire_due(datetime(2026, 11, 18, 9, 22)), ["Standup at 09:30 - Office"])
        finally:
            reminders.notify = real
        self.assertEqual(len(caught), 3)


class Ics(unittest.TestCase):
    def test_export_and_import_round_trip(self):
        evs = [A.add("Lunch; with Ana, Ivan", datetime(2026, 11, 20, 13, 0), 90, place="Кафе „Дунав“, София", notes="line one\nline two",
                     remind=30),
               A.add("Рожден ден на мама" + " много" * 20, datetime(2026, 12, 24), all_day=True, repeat="yearly", remind=None)]
        text = A.to_ics(evs)
        self.assertTrue(all(len(ln.encode("utf-8")) <= 75 for ln in text.split("\r\n")))  # folded as the standard asks
        self.assertIn("RRULE:FREQ=YEARLY", text)
        self.assertIn("TRIGGER:-PT30M", text)
        back = A.from_ics(text)
        self.assertEqual([(b["title"], b["start"], b["minutes"], b["all_day"], b["repeat"]) for b in back],
                         [("Lunch; with Ana, Ivan", datetime(2026, 11, 20, 13, 0), 90, False, ""),
                          (evs[1]["title"], datetime(2026, 12, 24), 1440, True, "yearly")])
        self.assertEqual((back[0]["place"], back[0]["notes"]), ("Кафе „Дунав“, София", "line one\nline two"))
        utc = A.from_ics("BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART:20260701T100000Z\nSUMMARY:Call\nEND:VEVENT\nEND:VCALENDAR")
        self.assertEqual(utc[0]["start"], datetime(2026, 7, 1, 10, 0, tzinfo=__import__("datetime").timezone.utc).astimezone().replace(tzinfo=None))
        self.assertEqual(A.from_ics("not a calendar"), [])


class Tools(unittest.TestCase):
    def setUp(self):
        (config.HOME / A.FILE).unlink(missing_ok=True)

    def test_add_list_move_cancel_and_undo(self):
        d = future(4)
        out = registry.execute(ctx(), "event_add", {"title": "Dentist", "when": d.strftime("%Y-%m-%d %H:%M"), "place": "Clinic"})
        self.assertIn("added [id ", out)
        eid = out.split("[id ")[1].split("]")[0]
        self.assertIn("Dentist (Clinic)", registry.execute(ctx(), "agenda", {"period": d.strftime("%Y-%m-%d")}))
        clash = registry.execute(ctx(), "event_add", {"title": "Call", "when": d.replace(minute=30).strftime("%Y-%m-%d %H:%M")})
        self.assertIn("overlaps", clash)
        self.assertIn("moved", registry.execute(ctx(), "event_move", {"id": eid, "when": (d + timedelta(days=1)).strftime("%Y-%m-%d")}))
        self.assertEqual(A.get(eid)["start"], A.iso(d + timedelta(days=1)))  # a day only: the same time of day
        undo.undo()
        self.assertEqual(A.get(eid)["start"], A.iso(d))
        self.assertIn("cancelled", registry.execute(ctx(), "event_cancel", {"id": eid}))
        self.assertIsNone(A.get(eid))
        undo.undo()
        self.assertIsNotNone(A.get(eid))
        self.assertTrue(registry.execute(ctx(), "event_add", {"title": "x", "when": "sometime"}).startswith("ERROR"))
        self.assertTrue(registry.execute(ctx(), "event_add", {"title": "x", "when": "2020-01-01 10:00"}).startswith("ERROR"))

    def test_a_date_without_a_time_is_all_day_and_repeats_are_understood(self):
        out = registry.execute(ctx(), "event_add", {"title": "Birthday", "when": "24 December", "repeat": "every year"})
        ev = A.find("Birthday")[0][1]
        self.assertEqual((ev["all_day"], ev["repeat"], ev["remind"]), (True, "yearly", None))
        self.assertIn("all day", out)

    def test_export_writes_an_ics_file_and_import_reads_one(self):
        A.add("Exported", future(2), 45)
        import re

        c = ctx()
        out = registry.execute(c, "calendar_export", {})
        path = re.search(r"created (.+?\.ics) \(", out).group(1)
        self.assertTrue(path.endswith(".ics"))
        (config.HOME / A.FILE).unlink()
        res = registry.execute(c, "calendar_import", {"path": path})
        self.assertIn("imported 1 events", res)
        self.assertIn("<untrusted_data", res)  # titles from a file are outside content
        self.assertEqual(A.find("Exported")[0][1]["minutes"], 45)


class FastAnswers(unittest.TestCase):
    def setUp(self):
        (config.HOME / A.FILE).unlink(missing_ok=True)

    def test_add_and_ask_without_the_model(self):
        h = intents.detect("Запиши среща със зъболекаря утре в 10")
        self.assertTrue(h.answer.startswith("Записах в календара: Среща със зъболекаря - Утре"))
        self.assertIn("10:00-11:00", h.answer)
        h = intents.detect("add a meeting with Ana to my calendar tomorrow at 15:00")
        self.assertIn("Meeting with Ana - Tomorrow", h.answer)
        h = intents.detect("Какво имам утре?")
        self.assertIn("Среща със зъболекаря", h.answer)
        self.assertNotIn("[id", h.answer)  # people are not shown internal ids
        self.assertIn("Meeting with Ana", intents.detect("what's on my calendar").answer)
        for q in ("what do I have to do to learn Spanish", "добави 2 и 2", "запиши среща с Иван", "какво имам да правя за python"):
            h = intents.detect(q)
            self.assertTrue(h is None or not (h.answer or "").startswith(("Записах", "Added", "Утре", "Tomorrow")), q)


class Api(unittest.TestCase):
    def setUp(self):
        (config.HOME / A.FILE).unlink(missing_ok=True)
        cfg = Config(provider="mock", output_dir=OUT, allowed_roots=[OUT])
        self.token = server.get_token()
        self.srv = server.serve(cfg, port=0)
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
            return 200, json.load(urllib.request.urlopen(req, timeout=10))
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            return e.code, json.loads(raw) if raw.startswith("{") else {}

    def test_the_panel_lists_adds_skips_cancels_and_exports(self):
        self.assertEqual(self.call("GET", "/calendar", token=False)[0], 401)
        d = future(2)
        code, r = self.call("POST", "/calendar", {"action": "add", "title": "Yoga", "date": d.strftime("%Y-%m-%d"), "time": "18:00",
                                                  "minutes": 60, "remind": 15, "repeat": "weekly"})
        self.assertEqual(code, 200)
        eid = r["event"]["id"]
        code, cal = self.call("GET", f"/calendar?from={d:%Y-%m-%d}&days=8")
        self.assertEqual([(x["date"], [e["title"] for e in x["events"]]) for x in cal["days"] if x["events"]],
                         [(f"{d:%Y-%m-%d}", ["Yoga"]), (f"{d + timedelta(days=7):%Y-%m-%d}", ["Yoga"])])
        first = cal["days"][0]["events"][0]["start"]
        self.assertEqual(self.call("POST", "/calendar", {"action": "skip", "id": eid, "start": first})[0], 200)
        code, cal = self.call("GET", f"/calendar?from={d:%Y-%m-%d}&days=8")
        self.assertEqual(sum(len(x["events"]) for x in cal["days"]), 1)
        code, r = self.call("POST", "/calendar", {"action": "add", "title": "Trip", "date": d.strftime("%Y-%m-%d"), "time": ""})
        self.assertTrue(r["event"]["all_day"])
        code, r = self.call("POST", "/calendar", {"action": "export"})
        self.assertTrue(r["ok"] and r["path"].endswith(".ics"))
        self.assertEqual(self.call("POST", "/calendar", {"action": "cancel", "id": eid})[0], 200)
        for bad in ({"action": "add", "title": "x", "date": "tomorrow"}, {"action": "add", "title": "", "date": f"{d:%Y-%m-%d}"},
                    {"action": "cancel", "id": "nope"}, {"action": "explode"}):
            self.assertEqual(self.call("POST", "/calendar", bad)[0], 400, bad)
        self.assertEqual(self.call("POST", "/calendar", {"action": "cancel", "id": eid}, origin="https://evil.example")[0], 403)


if __name__ == "__main__":
    unittest.main()
