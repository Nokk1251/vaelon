"""The Settings screen and first-run setup: what the app may read and change, and how keys are taken in.
Offline: a real local API server with a scripted model; nothing leaves the machine."""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

os.environ["VAELON_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vaelon import config, providers, server, settings  # noqa: E402
from vaelon.agent import Agent  # noqa: E402
from vaelon.config import Config  # noqa: E402
from vaelon.llm import MockLLM  # noqa: E402
from vaelon.memory import Memory  # noqa: E402

GROQ = "gsk_" + "t3stK3y" * 6  # shaped like a real key, made up for the test
FORGET = [n for n in settings.known_keys()]


class App(unittest.TestCase):
    def setUp(self):
        for n in FORGET:
            os.environ.pop(n, None)
            (config.HOME / "secrets" / f"key_{n}").unlink(missing_ok=True)
        from vaelon.security import dlp

        dlp.forget_cache()
        self.cfg = Config(provider="mock", allowed_roots=[tempfile.mkdtemp()])
        svc = server.Service(self.cfg, lambda cfg, approver: Agent(cfg, llm=MockLLM([]), approver=approver,
                                                                  memory=Memory(":memory:"), load_extensions=False))
        self.token = server.get_token()
        self.srv = server.serve(self.cfg, port=0, service=svc)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.real_pick, providers.pick_available = providers.pick_available, lambda cfg, name: None  # no network

    def tearDown(self):
        providers.pick_available = self.real_pick
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
            raw = urllib.request.urlopen(req, timeout=10).read().decode()
            return 200, json.loads(raw), raw
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            return e.code, (json.loads(raw) if raw.startswith("{") else {}), raw

    def test_settings_need_the_access_key_and_describe_the_state(self):
        self.assertEqual(self.call("GET", "/settings", token=False)[0], 401)
        self.assertEqual(self.call("POST", "/key", {"name": "GROQ_API_KEY", "value": GROQ}, token=False)[0], 401)
        code, s, _ = self.call("GET", "/settings")
        self.assertEqual(code, 200)
        self.assertTrue(s["first_run"])
        self.assertEqual([p["name"] for p in s["presets"]][:3], ["local", "groq", "gemini"])
        groq = next(p for p in s["presets"] if p["name"] == "groq")
        self.assertEqual((groq["key"], groq["key_set"], groq["cloud"]), ("GROQ_API_KEY", False, True))
        self.assertIn("TWELVEDATA_API_KEY", [k["name"] for k in s["keys"]])
        self.assertEqual(s["stock_sources"], ["Yahoo Finance"])
        self.assertEqual(s["search_sources"][-1], "Wikipedia")
        self.assertNotIn("Tavily", s["search_sources"])
        self.assertNotIn("ollama", s)  # the look at the local model server happens only when asked (?probe=1)
        self.assertEqual(self.call("GET", "/models")[1], {"models": ["qwen3:8b"], "error": None})

    def test_a_key_goes_into_the_vault_and_never_comes_back(self):
        code, body, raw = self.call("POST", "/key", {"name": "GROQ_API_KEY", "value": "  " + GROQ + "\n"})
        self.assertEqual((code, body["ok"]), (200, True))
        self.assertNotIn(GROQ, raw)
        self.assertEqual(config.env("GROQ_API_KEY"), GROQ)  # usable by the core ...
        sealed = (config.HOME / "secrets" / "key_GROQ_API_KEY").read_bytes()
        self.assertNotIn(GROQ.encode(), sealed)  # ... encrypted on disk ...
        for path in ("/settings", "/settings?probe=0", "/catalog", "/voice"):
            self.assertNotIn(GROQ, self.call("GET", path)[2])  # ... and in no answer of the API
        audit_log = (config.HOME / "audit.jsonl").read_text("utf-8")
        self.assertIn("key_set", audit_log)
        self.assertNotIn(GROQ, audit_log)
        row = next(k for k in self.call("GET", "/settings")[1]["keys"] if k["name"] == "GROQ_API_KEY")
        self.assertEqual((row["set"], row["stored"], row["age_days"], row["provider"]), (True, True, 0, "groq"))
        self.assertEqual(set(row), {"name", "what", "url", "provider", "set", "stored", "age_days"})  # no length, no tail
        code, body, _ = self.call("POST", "/key", {"name": "GROQ_API_KEY", "delete": True})
        self.assertTrue(body["ok"])
        self.assertEqual(config.env("GROQ_API_KEY"), "")

    def test_wrong_keys_and_foreign_pages_are_refused(self):
        secret = "sk-" + "wr0ngPlace" * 4
        for name, value, why in (("PATH", secret, "unknown key name"), ("VAULT_MASTER", secret, "unknown key name"),
                                 ("GROQ_API_KEY", secret, "start with 'gsk_'"), ("GEMINI_API_KEY", "short", "16-512"),
                                 ("GEMINI_API_KEY", "has a space inside it 123", "no spaces"),
                                 ("GEMINI_API_KEY", "", "empty"), ("GEMINI_API_KEY", None, "empty")):
            code, body, raw = self.call("POST", "/key", {"name": name, "value": value})
            self.assertEqual(code, 400, name)
            self.assertIn(why, body["error"])
            self.assertNotIn(secret, raw)
        self.assertFalse(any((config.HOME / "secrets").glob("key_PATH")))
        code, body, _ = self.call("POST", "/key", {"name": "GROQ_API_KEY", "value": GROQ}, origin="https://evil.example")
        self.assertEqual(code, 403)
        self.assertEqual(config.env("GROQ_API_KEY"), "")
        self.assertEqual(self.call("POST", "/settings", {"changes": {"address_as": "X"}}, origin="https://evil.example")[0], 403)
        self.assertEqual(self.call("POST", "/key", {"name": "GROQ_API_KEY", "value": GROQ}, origin="http://localhost:3100")[0], 200)

    def test_only_the_listed_settings_change_and_the_running_core_sees_them(self):
        code, body, _ = self.call("POST", "/settings", {"changes": {"address_as": "  Captain ", "auto_learn": False,
                                                                    "elevenlabs_monthly_chars": 500}})
        self.assertEqual((code, sorted(body["changed"])), (200, ["address_as", "auto_learn", "elevenlabs_monthly_chars"]))
        self.assertEqual((self.cfg.address_as, self.cfg.auto_learn, self.cfg.elevenlabs_monthly_chars), ("Captain", False, 500))
        self.assertEqual(Config.load().address_as, "Captain")  # saved too
        for changes, why in (({"allowed_roots": ["C:/"]}, "cannot be changed"), ({"auto_approve": ["shell"]}, "cannot be changed"),
                             ({"base_url": "https://evil.example/v1"}, "cannot be changed"),
                             ({"api_key_env": "X"}, "cannot be changed"), ({"address_as": ""}, "1-40"),
                             ({"model": "a b; rm"}, "model name"), ({"auto_learn": "yes"}, "on or off"),
                             ({"elevenlabs_monthly_chars": -1}, "0 to 1000000"), ({"setup_done": False}, "finished"),
                             ({"tts_engine": "elevenlabs"}, "ELEVENLABS_API_KEY"), ({"tts_engine": "siri"}, "unknown"),
                             ({"address_as": "Boss2", "allowed_roots": ["C:/"]}, "cannot be changed")):
            code, body, _ = self.call("POST", "/settings", {"changes": changes})
            self.assertEqual(code, 400, changes)
            self.assertIn(why, body["error"])
        self.assertEqual(self.cfg.address_as, "Captain")  # one bad field: nothing of that request was applied
        self.assertEqual(self.call("POST", "/settings", {"changes": "x"})[0], 400)

    def test_a_cloud_model_needs_its_key_first(self):
        code, body, _ = self.call("POST", "/settings", {"changes": {"provider": "groq"}})
        self.assertEqual((code, body["error"]), (400, "store the key GROQ_API_KEY first"))
        self.assertEqual(self.cfg.provider, "mock")
        self.call("POST", "/key", {"name": "GROQ_API_KEY", "value": GROQ})
        code, body, _ = self.call("POST", "/settings", {"changes": {"provider": "groq"}})
        self.assertEqual(code, 200)
        self.assertEqual((self.cfg.provider, self.cfg.base_url, self.cfg.api_key_env),
                         ("openai", "https://api.groq.com/openai/v1", "GROQ_API_KEY"))
        self.assertEqual((body["settings"]["preset"], body["settings"]["local"]), ("groq", False))
        code, body, _ = self.call("POST", "/settings", {"changes": {"model": "openai/gpt-oss-20b", "provider": "groq"}})
        self.assertEqual(self.cfg.model, "openai/gpt-oss-20b")  # an explicit model wins over the preset's
        code, body, _ = self.call("POST", "/settings", {"changes": {"provider": "local"}})
        self.assertEqual((self.cfg.provider, self.cfg.base_url, body["settings"]["local"]), ("ollama", "", True))

    def test_first_run_ends_once_and_old_installations_never_see_it(self):
        self.assertTrue(self.call("GET", "/settings")[1]["first_run"])
        self.call("POST", "/settings", {"changes": {"setup_done": True}})
        self.assertFalse(self.call("GET", "/settings")[1]["first_run"])
        self.assertTrue(Config.load().setup_done)
        Config.path().write_text(json.dumps({"provider": "ollama", "model": "qwen3:4b-instruct"}), "utf-8")
        self.assertTrue(Config.load().setup_done)  # written by a version without the setup: already in use
        Config.path().write_text(json.dumps({"provider": "ollama", "setup_done": False}), "utf-8")
        self.assertFalse(Config.load().setup_done)
        Config.path().unlink()
        self.assertFalse(Config.load().setup_done)  # a brand-new installation


if __name__ == "__main__":
    unittest.main()
