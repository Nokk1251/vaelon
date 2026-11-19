import json
import os
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
os.environ["VAELON_HOME"] = tempfile.mkdtemp()

from vaelon import config, scheduler, server
from vaelon.agent import Agent
from vaelon.config import Config
from vaelon.llm import LLM, LLMError, MockLLM
from vaelon.memory import Memory


class Flaky:
    """Fails like a down server, then answers."""

    def __init__(self, fail):
        self.fail, self.calls = fail, 0

    def chat(self, m):
        self.calls += 1
        if self.calls <= self.fail:
            raise LLMError("down")
        return '{"final":"ok"}'


class T(unittest.TestCase):
    def cfg(self):
        return Config(provider="mock", allowed_roots=[tempfile.mkdtemp()])

    def test_fallback_model(self):
        c = Config(provider="openai", model="x", base_url="http://127.0.0.1:1/v1",
                   fallbacks=[{"provider": "mock"}])
        l = LLM(c)
        calls = []
        orig = LLM._once
        LLM._once = lambda self, m, fmt=None, tools=None:(_ for _ in ()).throw(LLMError("down")) if self.cfg.provider != "mock" else "fallback-ok"
        import vaelon.llm as mod
        mod.time = time
        time_sleep, time.sleep = time.sleep, lambda s: None
        try:
            self.assertEqual(l.chat([{"role": "user", "content": "x"}]), "fallback-ok")
        finally:
            LLM._once = orig
            time.sleep = time_sleep

    def test_all_models_down_is_reported_not_crashed(self):
        a = Agent(self.cfg(), llm=Flaky(99), memory=Memory(":memory:"), load_extensions=False)
        self.assertIn("could not reach", a.run("hi"))

    def test_json_repair_once(self):
        llm = MockLLM(['{"tool": "now", "args": {', '{"final":"fixed"}'])
        a = Agent(self.cfg(), llm=llm, memory=Memory(":memory:"), load_extensions=False)
        self.assertEqual(a.run("x"), "fixed")

    def test_context_trim(self):
        c = self.cfg(); c.max_context_chars = 500
        a = Agent(c, llm=MockLLM([]), memory=Memory(":memory:"), load_extensions=False)
        msgs = [{"role": "system", "content": "s"}] + [{"role": "user", "content": "x" * 200}] * 10
        out = a._trim(msgs)
        self.assertEqual(out[0]["content"], "s")
        self.assertLess(len(out), len(msgs))

    def test_scheduler(self):
        j = scheduler.add("brief me", every_minutes=60)
        self.assertTrue(scheduler.is_due(scheduler.load()[0]))
        ran = scheduler.run_due(lambda: Agent(self.cfg(), llm=MockLLM(['{"final":"morning"}']),
                                              memory=Memory(":memory:"), load_extensions=False))
        self.assertEqual(ran, 1)
        self.assertEqual(scheduler.run_due(lambda: None), 0)  # not due again
        self.assertIn("morning", scheduler.inbox()[-1]["answer"])
        self.assertNotIn("morning", (config.HOME / "inbox.enc").read_text())  # results are stored encrypted
        self.assertTrue(scheduler.remove(j["id"]))
        with self.assertRaises(ValueError):
            scheduler.add("x")

    def test_daily_due(self):
        job = {"daily": "00:00", "last_run": 0}
        self.assertTrue(scheduler.is_due(job))
        job["last_run"] = time.time()
        self.assertFalse(scheduler.is_due(job))


class Streamer:
    def __init__(self, chunks):
        self.chunks = chunks

    def chat_stream(self, m):
        yield from self.chunks

    def chat(self, m):
        return "".join(self.chunks)


class Streaming(unittest.TestCase):
    def agent(self, llm):
        return Agent(Config(provider="mock", allowed_roots=[tempfile.mkdtemp()]), llm=llm,
                     memory=Memory(":memory:"), load_extensions=False)

    def test_plain_text_streams_token_by_token(self):
        ev = []
        out = self.agent(Streamer(["Hel", "lo ", "Boss."])).run("hi", on_event=lambda k, d: ev.append((k, d)))
        self.assertEqual(out, "Hello Boss.")
        self.assertEqual("".join(d for k, d in ev if k == "token"), "Hello Boss.")

    def test_json_tool_call_is_not_streamed(self):
        class Two(Streamer):
            n = 0
            def chat_stream(self, m):
                Two.n += 1
                yield from (['{"tool":"now",', '"args":{}}'] if Two.n == 1 else ["All ", "done."])
        ev = []
        out = self.agent(Two([])).run("time?", on_event=lambda k, d: ev.append((k, d)))
        self.assertEqual(out, "All done.")
        self.assertEqual([d for k, d in ev if k == "tool"], ["now"])
        self.assertEqual("".join(d for k, d in ev if k == "token"), "All done.")

    def test_json_final_still_supported(self):
        ev = []
        out = self.agent(Streamer(['{"final":"ok"}'])).run("x", on_event=lambda k, d: ev.append((k, d)))
        self.assertEqual(out, "ok")
        self.assertEqual("".join(d for k, d in ev if k == "token"), "ok")


class TTS(unittest.TestCase):
    def test_effect_is_bounded_and_changes_signal(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy not installed")
        from vaelon import tts
        t = np.linspace(0, 1, 16000, dtype=np.float32)
        x = 0.5 * np.sin(2 * np.pi * 150 * t)
        y = tts.vaelon_effect(x, 16000, 0.6)
        self.assertEqual(len(y), len(x))
        self.assertLessEqual(float(np.abs(y).max()), 1.0)
        self.assertFalse(np.allclose(x, y, atol=0.05))

    def test_wav_roundtrip(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy not installed")
        import io, wave
        from vaelon import tts
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes((np.sin(np.linspace(0, 200, 8000)) * 8000).astype(np.int16).tobytes())
        out = tts.apply_effect_wav(buf.getvalue())
        with wave.open(io.BytesIO(out)) as w:
            self.assertEqual(w.getnframes(), 8000)

    def test_lang_detect_and_missing_model(self):
        from vaelon import tts
        self.assertEqual(tts.detect_lang("Здравей"), "bg")
        self.assertEqual(tts.detect_lang("Hello"), "en")
        orig, tts._engine = tts._engine, lambda lang: None
        try:
            with self.assertRaises(FileNotFoundError):
                tts.synthesize("Hello")
        finally:
            tts._engine = orig


class Fast(unittest.TestCase):
    def test_time_and_date_without_model(self):
        from vaelon import fastpath
        t = time.strptime("2026-11-06 13:22", "%Y-%m-%d %H:%M")
        self.assertEqual(fastpath.try_answer("колко е часът?", t), "Часът е 13:22.")
        self.assertEqual(fastpath.try_answer("what time is it", t), "It is 13:22.")
        self.assertIn("петък, 6 ноември 2026", fastpath.try_answer("коя е датата днес", t))
        self.assertIsNone(fastpath.try_answer("напиши ми имейл", t))
        self.assertIsNone(fastpath.try_answer("какво е времето навън", t))

    def test_agent_uses_fastpath_not_llm(self):
        llm = MockLLM([])
        a = Agent(Config(provider="mock"), llm=llm, memory=Memory(":memory:"), load_extensions=False)
        self.assertTrue(a.run("колко е часът").startswith("Часът е"))
        self.assertEqual(llm.seen, [])


class API(unittest.TestCase):
    def setUp(self):
        c = Config(provider="mock", allowed_roots=[tempfile.mkdtemp()])
        self.tmp = Path(c.allowed_roots[0])
        self.file = self.tmp / "z.txt"
        self.file.write_text("keep")
        llm = MockLLM(['{"tool":"fs_delete_permanent","args":{"path":"%s"}}' % str(self.file).replace("\\", "/"),
                       '{"final":"finished"}'])
        svc = server.Service(c, lambda cfg, approver: Agent(cfg, llm=llm, approver=approver,
                                                           memory=Memory(":memory:"), load_extensions=False))
        self.token = server.get_token()
        self.srv = server.serve(c, port=0, service=svc)
        self.port = self.srv.server_address[1]
        import threading
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
            return json.load(urllib.request.urlopen(req, timeout=5))
        except urllib.error.HTTPError as e:
            return {"http": e.code}

    def test_cors_only_for_localhost(self):
        for origin, expect in (("http://localhost:3000", "http://localhost:3000"), ("https://evil.example", None)):
            req = urllib.request.Request(f"http://127.0.0.1:{self.port}/chat", method="OPTIONS", headers={"Origin": origin})
            r = urllib.request.urlopen(req, timeout=5)
            self.assertEqual(r.headers.get("Access-Control-Allow-Origin"), expect)

    def test_auth_required(self):
        self.assertEqual(self.call("POST", "/chat", {"text": "x"}, token=False), {"http": 401})
        self.assertTrue(self.call("GET", "/health")["ok"])

    def test_approval_flow_deny(self):
        jid = self.call("POST", "/chat", {"text": "delete it"})["job"]
        for _ in range(50):
            st = self.call("GET", f"/job/{jid}")
            if st["status"] == "approval":
                break
            time.sleep(0.1)
        self.assertEqual(st["status"], "approval")
        self.assertIn("PERMANENTLY", st["approval"]["summary"])
        # "Allow" without the id of the card shown (a stale card, a double click) approves nothing
        self.assertFalse(self.call("POST", "/approve", {"job": jid, "allow": True})["ok"])
        self.assertFalse(self.call("POST", "/approve", {"job": jid, "allow": True, "card": "wrong"})["ok"])
        self.assertTrue(st["approval"]["id"])
        self.assertTrue(self.call("POST", "/approve", {"job": jid, "allow": False})["ok"])
        for _ in range(50):
            st = self.call("GET", f"/job/{jid}")
            if st["status"] == "done":
                break
            time.sleep(0.1)
        self.assertEqual(st["answer"], "finished")
        self.assertTrue(self.file.exists())


if __name__ == "__main__":
    unittest.main()
