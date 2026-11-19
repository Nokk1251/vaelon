"""Several conversations: the encrypted store, the move from the single old history, and the app's API."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

os.environ["VAELON_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vaelon import config, conversation as C, server  # noqa: E402
from vaelon.agent import Agent  # noqa: E402
from vaelon.config import Config  # noqa: E402
from vaelon.llm import MockLLM  # noqa: E402
from vaelon.memory import Memory  # noqa: E402
from vaelon.security import vault  # noqa: E402


def turn(q, a):
    return [{"role": "user", "content": q}, {"role": "assistant", "content": a}]


class Store(unittest.TestCase):
    def setUp(self):
        C.wipe()

    def test_one_chat_at_first_and_its_title_is_the_first_question(self):
        first = C.current()
        self.assertEqual(C.current(), first)  # the same chat every time, not a new one per call
        self.assertEqual([(c["id"], c["title"], c["count"], c["current"]) for c in C.chats()], [(first, "", 0, True)])
        C.append(turn("[Attached file: C:/x/report.pdf]\nSummarise   the quarterly report please", "Here it is."))
        C.append(turn("And the second page?", "Also fine."))
        row = C.chats()[0]
        self.assertEqual((row["title"], row["count"]), ("Summarise the quarterly report please", 4))
        self.assertEqual([m["content"] for m in C.load(2)], ["And the second page?", "Also fine."])
        for f in (C.path(), C.path().parent / "index.enc"):
            raw = f.read_text("utf-8")
            self.assertNotIn("quarterly", raw)  # messages AND titles are encrypted on disk
            self.assertNotIn("Summarise", raw)

    def test_new_open_rename_delete(self):
        a = C.current()
        self.assertEqual(C.new(), a)  # an empty chat is reused: no pile of blanks
        C.append(turn("alpha question", "alpha answer"))
        b = C.new()
        self.assertNotEqual(a, b)
        self.assertEqual(C.load(), [])
        C.append(turn("beta question", "beta answer"))
        self.assertEqual([c["title"] for c in C.chats()], ["beta question", "alpha question"])  # newest first
        self.assertEqual([m["content"] for m in C.messages(a)], ["alpha question", "alpha answer"])
        self.assertTrue(C.open_chat(a))
        self.assertEqual(C.load()[0]["content"], "alpha question")
        C.append(turn("alpha again", "ok"))
        self.assertEqual(len(C.messages(a)), 4)
        self.assertEqual(len(C.messages(b)), 2)  # the other chat is untouched
        self.assertTrue(C.rename(b, "  Beta   plans  "))
        self.assertEqual(next(c["title"] for c in C.chats() if c["id"] == b), "Beta plans")
        self.assertFalse(C.rename(b, "   "))
        for bad in ("nope", "../../config", "", "zzzzzzzzzzzz"):
            self.assertFalse(C.open_chat(bad))
            self.assertFalse(C.delete(bad))
            self.assertIsNone(C.messages(bad))
        self.assertTrue(C.delete(a))  # deleting the open chat opens the newest one that is left
        self.assertEqual(C.current(), b)
        self.assertFalse(C.path(a).exists())
        self.assertTrue(C.delete(b))  # the last one: a fresh empty chat takes its place
        self.assertEqual([(c["title"], c["count"]) for c in C.chats()], [("", 0)])

    def test_clear_empties_only_the_open_chat_and_long_chats_are_trimmed(self):
        C.append(turn("keep me", "kept"))
        a = C.current()
        b = C.new()
        C.append(turn("erase me", "gone"))
        C.clear()
        self.assertEqual((C.load(), C.current()), ([], b))
        self.assertEqual(len(C.messages(a)), 2)
        for i in range(C.KEEP):
            C.append(turn(f"q{i}", f"a{i}"))
        self.assertLessEqual(C.count(), int(C.KEEP * 1.5))
        self.assertEqual(C.load(1)[0]["content"], f"a{C.KEEP - 1}")
        self.assertEqual(C.chats()[0]["count"], C.count())

    def test_the_history_of_an_older_version_becomes_the_first_chat(self):
        old = config.HOME / C.FILE
        lines = [vault.encrypt_text(json.dumps(m, ensure_ascii=False)) for m in turn("Здравей, Вейлон", "Здравей.")]
        old.write_text("\n".join(lines) + "\n", "utf-8")
        self.assertEqual([m["content"] for m in C.load()], ["Здравей, Вейлон", "Здравей."])
        self.assertFalse(old.exists())  # moved, not copied
        self.assertEqual(C.path().read_text("utf-8").splitlines(), lines)  # as it was: nothing re-encrypted
        self.assertEqual([(c["title"], c["count"]) for c in C.chats()], [("Здравей, Вейлон", 2)])

    def test_a_lost_index_does_not_lose_the_chats(self):
        C.append(turn("first chat", "yes"))
        a = C.current()
        C.new()
        C.append(turn("second chat", "yes"))
        (C.path().parent / "index.enc").write_text("garbage", "utf-8")
        self.assertEqual(sorted(c["title"] for c in C.chats()), ["first chat", "second chat"])
        self.assertEqual(len(C.messages(a)), 2)

    def test_the_app_opens_on_a_new_conversation(self):
        from vaelon import desktop

        C.append(turn("yesterday's question", "yesterday's answer"))
        old = C.current()
        real_serve, real_running = desktop.server.serve, desktop._core_running
        desktop.server.serve = lambda cfg: type("S", (), {"serve_forever": lambda self: None})()
        desktop._core_running = lambda port: False
        try:
            desktop.start_core(Config(provider="mock"))
        finally:
            desktop.server.serve, desktop._core_running = real_serve, real_running
        self.assertNotEqual(C.current(), old)
        self.assertEqual(C.load(), [])
        self.assertEqual(len(C.messages(old)), 2)  # still there, one click away in the list
        self.assertEqual([c["title"] for c in C.chats() if not c["current"]], ["yesterday's question"])

    def test_wipe_removes_everything(self):
        C.append(turn("secret plan", "noted"))
        C.new()
        C.wipe()
        self.assertEqual(list((config.HOME / C.DIR).glob("*.enc")), [])
        self.assertEqual([(c["title"], c["count"]) for c in C.chats()], [("", 0)])


class Api(unittest.TestCase):
    def setUp(self):
        C.wipe()
        self.root = Path(tempfile.mkdtemp())
        self.file = self.root / "z.txt"
        self.file.write_text("keep")
        cfg = Config(provider="mock", allowed_roots=[str(self.root)])
        self.llm = MockLLM([])
        self.agents = []

        def make(c, approver):
            a = Agent(c, llm=self.llm, approver=approver, memory=Memory(":memory:"), load_extensions=False)
            a.persist, a.use_intents = True, False
            a.history[:] = C.load(12)
            self.agents.append(a)
            return a

        self.svc = server.Service(cfg, make)
        self.token = server.get_token()
        self.srv = server.serve(cfg, port=0, service=self.svc)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def call(self, method, path, body=None, token=True):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None)
        if token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            return 200, json.load(urllib.request.urlopen(req, timeout=10))
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            return e.code, json.loads(raw) if raw.startswith("{") else {}

    def ask(self, text, reply, wait="done"):
        self.llm.replies.append(reply)
        jid = self.call("POST", "/chat", {"text": text})[1]["job"]
        for _ in range(100):
            st = self.call("GET", f"/job/{jid}")[1]
            if st["status"] == wait:
                return jid, st
            time.sleep(0.05)
        self.fail(f"job never reached {wait}")

    def test_the_app_lists_switches_and_shows_chats(self):
        self.assertEqual(self.call("GET", "/chats", token=False)[0], 401)
        self.assertEqual(self.call("POST", "/chats", {"action": "new"}, token=False)[0], 401)
        self.ask("Plan my trip to Rome", '{"final": "Three days is enough."}')
        code, body = self.call("GET", "/chats")
        self.assertEqual([(c["title"], c["count"], c["current"]) for c in body["chats"]], [("Plan my trip to Rome", 2, True)])
        rome = body["chats"][0]["id"]
        code, body = self.call("POST", "/chats", {"action": "new"})
        self.assertEqual((code, body["messages"], len(body["chats"])), (200, [], 2))
        self.assertEqual(self.agents[0].history, [])  # the model no longer sees the Rome talk
        self.ask("What is a quasar?", '{"final": "A very bright galactic core."}')
        self.assertFalse(any("Rome" in str(m) for m in self.llm.seen[-1]))
        code, body = self.call("POST", "/chats", {"action": "open", "id": rome})
        self.assertEqual([m["content"] for m in body["messages"]], ["Plan my trip to Rome", "Three days is enough."])
        self.assertEqual(body["current"], rome)
        self.ask("And the food?", '{"final": "Carbonara."}')
        self.assertTrue(any("Plan my trip to Rome" in str(m) for m in self.llm.seen[-1]))  # the context came back
        self.assertFalse(any("quasar" in str(m) for m in self.llm.seen[-1]))
        code, body = self.call("GET", f"/chats/{rome}")
        self.assertEqual(len(body["messages"]), 4)
        self.assertEqual(self.call("GET", "/chats/ffffffffffff")[0], 404)
        self.assertEqual(self.call("GET", "/chats/..%2F..%2Fconfig")[0], 404)
        self.assertEqual(self.call("POST", "/chats", {"action": "open", "id": "nope"})[0], 404)
        self.assertEqual(self.call("POST", "/chats", {"action": "explode"})[0], 400)
        code, body = self.call("POST", "/chats", {"action": "rename", "id": rome, "title": "Rome"})
        self.assertIn("Rome", [c["title"] for c in body["chats"]])
        code, body = self.call("POST", "/chats", {"action": "delete", "id": rome})
        self.assertEqual([c["title"] for c in body["chats"]], ["What is a quasar?"])
        self.assertEqual(self.agents[0].history[0]["content"], "What is a quasar?")  # the remaining chat is open

    def test_no_switching_while_a_task_is_running(self):
        self.ask("hello", '{"final": "hi"}')
        first = C.current()
        jid, _ = self.ask("delete the file", '{"tool":"fs_delete_permanent","args":{"path":"%s"}}'
                          % str(self.file).replace("\\", "/"), wait="approval")
        for action in ({"action": "new"}, {"action": "open", "id": first}, {"action": "delete", "id": first}):
            code, body = self.call("POST", "/chats", action)
            self.assertEqual((code, body["ok"]), (409, False))
        self.assertEqual(C.current(), first)
        self.assertEqual(self.call("POST", "/chats", {"action": "rename", "id": first, "title": "Greeting"})[0], 200)
        self.call("POST", "/approve", {"job": jid, "allow": False})
        for _ in range(100):
            if self.call("GET", f"/job/{jid}")[1]["status"] == "done":
                break
            time.sleep(0.05)
        self.assertEqual(self.call("POST", "/chats", {"action": "new"})[0], 200)
        self.assertTrue(self.file.exists())


if __name__ == "__main__":
    unittest.main()
