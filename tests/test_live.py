"""Live voice bridge: the messages it builds and reads, and how a spoken request reaches the normal agent.
Offline: no connection to Google is made."""
import base64
import os
import sys
import tempfile
import time
import unittest

os.environ["VAELON_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vaelon import live, server  # noqa: E402
from vaelon.agent import Agent  # noqa: E402
from vaelon.config import Config  # noqa: E402
from vaelon.llm import MockLLM  # noqa: E402
from vaelon.memory import Memory  # noqa: E402


class Messages(unittest.TestCase):
    def test_setup_gives_the_model_one_function_and_no_key(self):
        cfg = Config(provider="mock", address_as="Boss")
        setup = live.setup_message(cfg)["setup"]
        self.assertEqual(setup["model"], "models/gemini-3.1-flash-live-preview")
        self.assertEqual(setup["generationConfig"]["responseModalities"], ["AUDIO"])
        names = [f["name"] for f in setup["tools"][0]["functionDeclarations"]]
        self.assertEqual(names, ["ask_vaelon"])  # everything real goes through the normal agent
        text = setup["systemInstruction"]["parts"][0]["text"]
        self.assertIn("Boss", text)
        self.assertIn("ask_vaelon", text)
        self.assertIn("inputAudioTranscription", setup)
        self.assertNotIn("key", str(setup).lower().replace("ask_vaelon", ""))

    def test_audio_screen_and_text_messages(self):
        pcm = b"\x01\x02\x03\x04"
        audio = live.audio_message(pcm)["realtimeInput"]["audio"]
        self.assertEqual(audio["mimeType"], "audio/pcm;rate=16000")
        self.assertEqual(base64.b64decode(audio["data"]), pcm)
        frame = live.frame_message(b"JPEG")["realtimeInput"]["video"]
        self.assertEqual((frame["mimeType"], base64.b64decode(frame["data"])), ("image/jpeg", b"JPEG"))
        self.assertTrue(live.text_message("hi")["clientContent"]["turnComplete"])
        resp = live.tool_response("7", "ask_vaelon", "Sunny")["toolResponse"]["functionResponses"][0]
        self.assertEqual((resp["id"], resp["response"]["result"]), ("7", "Sunny"))

    def test_messages_from_google_become_simple_events(self):
        self.assertEqual(live.parse({"setupComplete": {}}), [("ready",)])
        msg = {"serverContent": {"modelTurn": {"parts": [{"inlineData": {"mimeType": "audio/pcm", "data": base64.b64encode(b"abcd").decode()}}]},
                                 "inputTranscription": {"text": "what time"}, "outputTranscription": {"text": "It is"},
                                 "turnComplete": True}}
        self.assertEqual(live.parse(msg), [("audio", b"abcd"), ("you", "what time"), ("say", "It is"), ("turn",)])
        self.assertEqual(live.parse({"serverContent": {"interrupted": True}}), [("interrupted",)])
        call = {"toolCall": {"functionCalls": [{"id": "c1", "name": "ask_vaelon", "args": {"request": "weather in Varna"}}]}}
        self.assertEqual(live.parse(call), [("call", "c1", "ask_vaelon", {"request": "weather in Varna"})])
        self.assertEqual(live.parse({}), [])
        self.assertEqual(live.parse({"goAway": {}})[0][0], "closing")


class SpokenRequest(unittest.TestCase):
    def service(self, replies):
        def make(c, approver):
            a = Agent(c, llm=MockLLM(replies), approver=approver, memory=Memory(":memory:"), load_extensions=False)
            a.use_intents = False
            return a

        return server.Service(Config(provider="mock"), make)

    def test_a_request_runs_as_a_normal_job_and_returns_the_answer(self):
        svc = self.service(['{"tool": "now", "args": {}}', '{"final": "It is ten past four."}'])
        notes = []
        answer = live.ask_vaelon(svc, "run the check and report back", False, notes.append)
        self.assertEqual(answer, "It is ten past four.")
        kinds = [n["type"] for n in notes]
        self.assertEqual((kinds[0], kinds[-1]), ("task", "task_done"))
        self.assertIn({"type": "tool", "name": "now"}, notes)
        self.assertEqual(len(svc.agent().history), 2)  # it is part of the one shared conversation

    def test_a_task_that_finished_at_once_still_reports_its_tool(self):  # the loop never saw it running
        class Job:
            status, tool, files, cancelled, answer, rev, approval = "done", "now", [], False, "Done.", 3, None

            def wait_change(self, rev, timeout):
                pass

        class Svc:
            jobs = {"j1": Job()}

            def start(self, request, spoken=False, screen=False):
                return "j1"

        notes = []
        self.assertEqual(live.ask_vaelon(Svc(), "quick one", False, notes.append), "Done.")
        self.assertIn({"type": "tool", "name": "now"}, notes)
        self.assertEqual((notes[0]["type"], notes[-1]["type"]), ("task", "task_done"))

    def test_dangerous_actions_still_need_the_approval_card(self):
        root = tempfile.mkdtemp()
        victim = os.path.join(root, "keep.txt")
        open(victim, "w").write("keep")
        svc = self.service(['{"tool": "fs_delete_permanent", "args": {"path": "%s"}}' % victim.replace("\\", "/"),
                            '{"final": "I did not delete it."}'])
        svc.cfg.allowed_roots = [root]
        notes = []

        def notify(n):
            notes.append(n)
            if n["type"] == "approval":
                svc.approve(n["job"], False)  # the user presses Deny in the small window

        answer = live.ask_vaelon(svc, "delete keep.txt forever", False, notify)
        self.assertTrue(any(n["type"] == "approval" for n in notes))
        self.assertTrue(os.path.exists(victim))
        self.assertEqual(answer, "I did not delete it.")

    def test_a_cancelled_request_says_so(self):
        class Slow:
            def chat_stream(self, messages, **kw):
                for _ in range(200):
                    time.sleep(0.02)
                    yield "word "

            def chat(self, messages):
                return "x"

        def make(c, approver):
            a = Agent(c, llm=Slow(), approver=approver, memory=Memory(":memory:"), load_extensions=False)
            a.use_intents = False
            return a

        svc = server.Service(Config(provider="mock"), make)

        def notify(n):
            if n["type"] == "task":
                import threading

                threading.Timer(0.3, lambda: svc.cancel(n["job"])).start()

        self.assertEqual(live.ask_vaelon(svc, "tell a long story", False, notify), "The user cancelled this request.")


class Status(unittest.TestCase):
    def test_live_needs_a_key(self):
        saved = os.environ.pop("GEMINI_API_KEY", None)
        try:
            self.assertFalse(live.available())
            self.assertFalse(live.status(Config(provider="mock"))["key"])
            os.environ["GEMINI_API_KEY"] = "test-not-a-real-key-0000"
            self.assertEqual(live.available(), live.websockets is not None)
        finally:
            os.environ.pop("GEMINI_API_KEY", None)
            if saved is not None:
                os.environ["GEMINI_API_KEY"] = saved

    def test_the_page_may_only_reach_local_bridges(self):
        self.assertIn("ws://127.0.0.1:*", server.CSP)
        self.assertNotIn("wss:", server.CSP)  # the page itself can never talk to an outside server


if __name__ == "__main__":
    unittest.main()
