"""Speed helpers: the shared keep-alive pool and its warm-up, the voices warming up side by side, job timing.
Offline: no connection is really opened and no voice model is loaded."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

os.environ["VAELON_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import requests  # noqa: E402

from vaelon import llm, server, speed, stt, tts  # noqa: E402
from vaelon.agent import Agent  # noqa: E402
from vaelon.config import Config  # noqa: E402
from vaelon.llm import MockLLM  # noqa: E402
from vaelon.memory import Memory  # noqa: E402

GROQ = Config(provider="openai", base_url="https://api.groq.com/openai/v1", api_key_env="GROQ_API_KEY")


class Connections(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.fail = False
        self.real = speed.HTTP.head

        def head(url, **kw):
            self.calls.append((url, kw))
            if self.fail:
                raise requests.ConnectionError("offline")

        speed.HTTP.head = head
        speed._last.clear()
        for k in ("GROQ_API_KEY", "ELEVENLABS_API_KEY"):
            os.environ.pop(k, None)

    def tearDown(self):
        speed.HTTP.head = self.real
        speed._last.clear()
        for k in ("GROQ_API_KEY", "ELEVENLABS_API_KEY"):
            os.environ.pop(k, None)

    def settle(self):
        for t in threading.enumerate():
            if t.name == "vaelon-warm":
                t.join(2)

    def test_one_pool_serves_the_model_the_microphone_and_the_cloud_voice(self):
        self.assertIs(llm._http, speed.HTTP)
        self.assertFalse(hasattr(stt, "_http"))
        self.assertFalse(hasattr(tts, "_el_http"))
        self.assertFalse(speed.HTTP.headers.get("Authorization"))  # a key is never a default of the shared pool
        self.assertFalse(speed.HTTP.headers.get("xi-api-key"))

    def test_a_fully_local_setup_opens_nothing(self):
        self.assertEqual(speed.targets(Config()), [])
        self.assertEqual(speed.warm(Config()), [])
        self.assertEqual(speed.targets(Config(provider="openai", base_url="http://127.0.0.1:1234/v1")), [])
        self.assertEqual(self.calls, [])

    def test_only_the_services_already_chosen_are_opened_and_nothing_is_sent(self):
        os.environ["GROQ_API_KEY"] = "gsk_test_key_0000000000001"
        self.assertEqual(speed.targets(GROQ), ["https://api.groq.com"])  # speech-to-text and model: one host, once
        os.environ["ELEVENLABS_API_KEY"] = "sk_test_key_00000000000001"
        both = Config(provider="openai", base_url=GROQ.base_url, api_key_env="GROQ_API_KEY", tts_engine="elevenlabs")
        self.assertEqual(speed.warm(both), ["https://api.groq.com", "https://api.elevenlabs.io"])
        self.settle()
        self.assertEqual(sorted(u for u, _ in self.calls), ["https://api.elevenlabs.io/", "https://api.groq.com/"])
        for _, kw in self.calls:  # an empty request: no key, no text, no audio, no following of redirects
            self.assertEqual(set(kw), {"timeout", "allow_redirects"})
            self.assertFalse(kw["allow_redirects"])
        self.assertEqual(speed.targets(Config(provider="openai", base_url=GROQ.base_url, tts_engine="piper")),
                         ["https://api.groq.com"])

    def test_a_fresh_connection_is_left_alone_and_a_failed_one_is_tried_again(self):
        os.environ["GROQ_API_KEY"] = "gsk_test_key_0000000000001"
        self.assertEqual(speed.warm(GROQ), ["https://api.groq.com"])
        self.settle()
        self.assertEqual(speed.warm(GROQ), [])  # opened a moment ago
        speed._last["https://api.groq.com"] -= speed.FRESH + 1
        self.assertEqual(speed.warm(GROQ), ["https://api.groq.com"])  # the service has closed it by now
        self.settle()
        speed._last.clear()
        speed.used("https://api.groq.com/openai/v1/chat/completions")  # a real call just went there
        self.assertEqual(speed.warm(GROQ), [])
        speed._last.clear()
        self.fail = True
        speed.warm(GROQ)
        self.settle()
        self.fail = False
        self.assertEqual(speed.warm(GROQ), ["https://api.groq.com"])  # the failure was not remembered as "open"


class Voices(unittest.TestCase):
    def test_both_voices_warm_up_at_once_with_a_real_word(self):
        said, gate, inside = [], threading.Event(), []
        real_piper, real_engine = tts._piper, tts._engine

        def fake_piper(text, lang, *a, **k):
            inside.append(lang)
            gate.wait(3)  # the first voice is still loading: the second must already be inside too
            said.append((lang, text))
            return b""

        tts._piper, tts._engine = fake_piper, lambda lang: "piper"
        tts.READY.clear()
        try:
            tts.warmup()
            for _ in range(100):
                if len(inside) == 2:
                    break
                time.sleep(0.02)
            self.assertEqual(sorted(inside), ["bg", "en"])  # side by side, not one after the other
            gate.set()
            for _ in range(100):
                if len(tts.READY) == 2:
                    break
                time.sleep(0.02)
            self.assertEqual(sorted(said), [("bg", "Готово."), ("en", "Ready.")])  # a word, so the model really runs once
            self.assertEqual(sorted(tts.READY), ["bg", "en"])
        finally:
            gate.set()
            tts._piper, tts._engine = real_piper, real_engine
        self.assertIs(tts._voice_lock("en"), tts._voice_lock("en"))
        self.assertIsNot(tts._voice_lock("en"), tts._voice_lock("bg"))

    def test_the_voices_wait_for_the_window_so_the_start_is_not_slowed(self):
        real_piper, real_engine = tts._piper, tts._engine
        loaded = []
        tts._piper, tts._engine = (lambda text, lang, *a, **k: loaded.append(lang) or b""), (lambda lang: "piper")
        tts.UI_UP.clear()
        try:
            time.sleep(0.1)
            loaded.clear()
            tts.warmup(wait=5)
            time.sleep(0.3)
            self.assertEqual(loaded, [])  # the app is still starting: nothing competes with it
            tts.UI_UP.set()  # the window asked for its page
            for _ in range(100):
                if len(set(loaded)) == 2:
                    break
                time.sleep(0.02)
            # (a set: warm-ups started by other tests' servers in this file may be released by the same signal)
            self.assertEqual(set(loaded), {"bg", "en"})
            time.sleep(0.2)
            loaded.clear()
            tts.UI_UP.clear()
            tts.warmup(wait=0.2)  # no window at all (`vaelon daemon`): they load after the wait anyway
            time.sleep(0.7)
            self.assertEqual(set(loaded), {"bg", "en"})
        finally:
            tts.UI_UP.set()
            tts._piper, tts._engine = real_piper, real_engine

    def test_a_cloud_voice_is_not_loaded_locally(self):
        real_piper, real_engine = tts._piper, tts._engine
        called = []
        tts._piper, tts._engine = (lambda *a, **k: called.append(a)), (lambda lang: "elevenlabs")
        try:
            tts.warmup()
            time.sleep(0.2)
            self.assertEqual(called, [])  # nothing is spoken (and no credit is spent) just to warm up
        finally:
            tts._piper, tts._engine = real_piper, real_engine


class Name(unittest.TestCase):
    """Speech recognition writes "Vaelon" as "Valon": the model then believed that was its name."""

    def test_the_name_is_hinted_and_corrected(self):
        sent = []

        class R:
            def raise_for_status(self):
                pass

            def json(self):
                return {"text": "You are not Valon, you are Valon."}

        real_post, real_engine = speed.HTTP.post, stt.engine
        speed.HTTP.post = lambda url, **kw: sent.append(kw) or R()
        stt.engine = lambda cfg=None: "groq"
        try:
            self.assertEqual(stt.transcribe(b"RIFF....", "audio/wav"), "You are not Vaelon, you are Vaelon.")
        finally:
            speed.HTTP.post, stt.engine = real_post, real_engine
        self.assertEqual(sent[0]["data"]["prompt"], "Vaelon")
        self.assertEqual(stt.fix_name("Валон, колко е часът?"), "Вейлон, колко е часът?")
        for wrong in ("Waelon", "Welon", "Walon", "Vealon", "VALON", "WAELON"):  # the owner's list, 2026-11-15
            self.assertEqual(stt.fix_name(f"{wrong}, what time is it?"), "Vaelon, what time is it?", wrong)
        self.assertEqual(stt.fix_name("Уейлон, здравей"), "Вейлон, здравей")
        self.assertEqual(stt.fix_name("Waylon Jennings and the Walloon language"), "Waylon Jennings and the Walloon language")
        from vaelon.agent import PERSONA

        self.assertIn("Valon", PERSONA)  # the model is told what the misspelling means


class SpokenLookup(unittest.TestCase):
    """The Wikipedia pre-fetch costs about half a second: worth it for a small local model and for people,
    not for a spoken "what is ..." answered by a cloud model."""

    def setUp(self):
        from vaelon.tools import registry

        registry.load_builtin()
        self.tool = registry.REGISTRY["wiki"]
        self.real = self.tool.func
        self.calls = []

        def fake(ctx, topic, lang="en"):
            self.calls.append((topic, bool(ctx.extra.get("hurry"))))
            return "A black hole is a region of spacetime."

        self.tool.func = fake

    def tearDown(self):
        self.tool.func = self.real

    def ask(self, cfg, text, spoken):
        a = Agent(cfg, llm=MockLLM(['{"final": "ok"}']), memory=Memory(":memory:"), load_extensions=False)
        a.use_intents = True
        self.calls.clear()
        a.run(text, spoken=spoken)
        return list(self.calls)

    def test_only_spoken_concept_questions_to_a_cloud_model_skip_the_lookup(self):
        cloud = Config(provider="openai", base_url="https://api.groq.com/openai/v1")
        self.assertEqual(self.ask(cloud, "What is a black hole?", spoken=True), [])
        self.assertEqual(self.ask(cloud, "Какво е черна дупка?", spoken=True), [])
        self.assertEqual(self.ask(cloud, "What is a black hole?", spoken=False), [("a black hole", False)])  # typed: sourced
        self.assertEqual(self.ask(cloud, "Who is Nikola Tesla?", spoken=True), [("Nikola Tesla", True)])  # a person: looked up
        self.assertEqual(self.ask(cloud, "Кой е Христо Ботев?", spoken=True), [("Христо Ботев", True)])
        self.assertEqual(self.ask(Config(provider="mock"), "What is a black hole?", spoken=True), [("a black hole", True)])  # local model


class Api(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(provider="mock")
        llm_ = MockLLM(['{"final": "Paris."}'])
        svc = server.Service(self.cfg, lambda c, approver: Agent(c, llm=llm_, approver=approver, memory=Memory(":memory:"),
                                                               load_extensions=False))
        self.token = server.get_token()
        self.srv = server.serve(self.cfg, port=0, service=svc)
        tts.UI_UP.set()  # let this server's own voice warm-up finish now (no voices here): none is left waiting
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
            return e.code, {}

    def test_warm_needs_the_access_key_and_a_job_reports_when_its_first_words_came(self):
        self.assertEqual(self.call("POST", "/warm", {}, token=False)[0], 401)
        self.assertEqual(self.call("POST", "/warm", {}), (200, {"ok": True, "warming": []}))  # local setup: nothing to open
        jid = self.call("POST", "/chat", {"text": "capital of France?"})[1]["job"]
        for _ in range(100):
            st = self.call("GET", f"/job/{jid}")[1]
            if st["status"] == "done":
                break
            time.sleep(0.05)
        self.assertEqual(st["answer"], "Paris.")
        self.assertIsInstance(st["first_after"], float)
        self.assertLessEqual(0, st["first_after"])
        self.assertLessEqual(st["first_after"], st["elapsed"] + 0.1)


if __name__ == "__main__":
    unittest.main()
