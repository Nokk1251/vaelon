import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
os.environ["VAELON_HOME"] = tempfile.mkdtemp()

from vaelon import config, guardian, router, server
from vaelon.agent import Agent
from vaelon.config import Config
from vaelon.memory import Memory
from vaelon.tools import registry
from vaelon.tools.registry import Ctx

registry.load_builtin()


class Router(unittest.TestCase):
    def test_routes_by_intent_in_two_languages(self):
        self.assertIn("send_email", router.route("изпрати мейл на мама"))
        self.assertIn("fs_move", router.route("move the report to Desktop"))
        self.assertIn("security_audit", router.route("провери компютъра за вируси"))
        self.assertNotIn("send_email", router.route("подреди папката"))
        self.assertTrue(router.CORE <= router.route("здрасти"))

    def test_more_tools_unlocks_and_rebuilds_prompt(self):
        class Two:
            supports_schema = True

            def __init__(self):
                self.prompts = []
                self.replies = ['{"tool":"more_tools","args":{"need":"send an email"},"answer":""}',
                                '{"tool":"none","args":{},"answer":"ok"}']

            def chat(self, msgs, fmt=None):
                self.prompts.append((msgs[0]["content"], fmt))
                return self.replies.pop(0)

        llm = Two()
        a = Agent(Config(provider="mock"), llm=llm, memory=Memory(":memory:"), load_extensions=False)
        self.assertEqual(a.run("hello there"), "ok")
        self.assertNotIn("send_email", llm.prompts[0][1]["properties"]["tool"]["enum"])
        self.assertIn("send_email", llm.prompts[1][1]["properties"]["tool"]["enum"])
        self.assertIn("send_email", llm.prompts[1][0])

    def test_static_prompt_is_stable_and_context_goes_to_user_turn(self):
        a = Agent(Config(provider="mock"), llm=None, memory=Memory(":memory:"), load_extensions=False)
        a.memory.add("Boss likes dark mode")
        active = router.route("dark mode")
        self.assertEqual(a._system(None, active), a._system(None, active))
        self.assertNotIn("dark mode", a._system(None, active))
        self.assertIn("dark mode", a._context("dark mode"))


class Coding(unittest.TestCase):
    def test_writes_verifies_and_self_corrects(self):
        class Coder:
            calls = 0

            def chat(self, msgs, fmt=None):
                Coder.calls += 1
                if Coder.calls == 1:
                    return "```python\ndef add(a, b)\n    return a + b\n```"  # syntax error
                assert "FAILED THE CHECK" in msgs[0]["content"]
                return "```python\ndef add(a, b):\n    return a + b\n```"

        tmp = tempfile.mkdtemp()
        ag = Agent(Config(provider="mock", allowed_roots=[tmp]), llm=Coder(), memory=Memory(":memory:"),
                   load_extensions=False)
        ctx = Ctx(ag.cfg, ag.memory, lambda r: True)
        ctx.extra["agent"] = ag
        out = registry.execute(ctx, "code_task", {"path": str(Path(tmp, "m.py")), "instructions": "add function"})
        self.assertTrue(out.startswith("VERIFIED"), out)
        self.assertIn("round 1: failed; round 2: passed", out)
        self.assertTrue(any("Lesson (coding .py)" in t for _, t in ag.memory.recent()))
        registry.execute(ctx, "undo", {})
        self.assertFalse(Path(tmp, "m.py").exists())


class Guardian(unittest.TestCase):
    def test_url_heuristics(self):
        self.assertEqual(guardian.url_risk("https://github.com/ollama/ollama")[0], 0)
        self.assertGreaterEqual(guardian.url_risk("http://paypal-login.verify-account.xyz/signin")[0], 3)
        self.assertGreaterEqual(guardian.url_risk("http://93.184.216.34/setup.exe")[0], 3)
        self.assertGreater(guardian.url_risk("https://bit.ly/x")[0], 0)

    def test_content_patterns(self):
        found = guardian.content_risk('<script>eval(atob("x"))</script> Your computer is infected! call Microsoft support')
        self.assertIn("obfuscated JavaScript execution", found)
        self.assertIn("tech-support scam text", found)
        self.assertEqual(guardian.content_risk("<p>hello</p>"), [])

    def test_web_layer_blocks_malicious_links(self):
        from vaelon.tools import web

        with self.assertRaises(ValueError):
            web._guard("http://paypal-login.verify-account.xyz/signin")

    def test_scan_file_reports(self):
        tmp = tempfile.mkdtemp()
        Path(tmp, "a.txt").write_text("hello")
        ctx = Ctx(Config(provider="mock", allowed_roots=[tmp]), Memory(":memory:"))
        out = registry.execute(ctx, "scan_file", {"path": str(Path(tmp, "a.txt"))})
        self.assertTrue(out.startswith(("CLEAN", "NOT SCANNED")), out)


class Extensions(unittest.TestCase):
    def test_disable_enable_cycle(self):
        plug = config.HOME / "plugins"
        plug.mkdir(parents=True, exist_ok=True)
        (plug / "hello.py").write_text("from vaelon.tools.registry import tool\n@tool('hello_x','hi')\ndef f(ctx): return 'hi'\n")
        ctx = Ctx(Config(provider="mock"), Memory(":memory:"), approver=lambda r: True)
        self.assertIn("hello [enabled] OK", registry.execute(ctx, "extension_list", {}))
        registry.execute(ctx, "extension_disable", {"name": "hello"})
        self.assertIn("hello [disabled]", registry.execute(ctx, "extension_list", {}))
        registry.execute(ctx, "extension_enable", {"name": "hello"})
        self.assertTrue((plug / "hello.py").exists())


class GitHubResearch(unittest.TestCase):
    def test_records_licence_and_reuse_policy(self):
        from vaelon.tools import github

        orig_top, orig_gh = github.top_repos, github._gh
        github.top_repos = lambda topic, language="", limit=3: [
            {"name": "a/permissive", "stars": 900, "url": "https://github.com/a/permissive", "license": "MIT", "desc": ""},
            {"name": "b/closed", "stars": 50, "url": "https://github.com/b/closed", "license": "none", "desc": ""}]
        github._gh = lambda path, raw=False, params=None: "README text"

        class L:
            def chat(self, msgs, fmt=None):
                return '{"facts": ["Cache the system prompt prefix for speed."]}'

        try:
            ag = Agent(Config(provider="mock"), llm=L(), memory=Memory(":memory:"), load_extensions=False)
            ctx = Ctx(ag.cfg, ag.memory)
            ctx.extra["agent"] = ag
            out = registry.execute(ctx, "research_code", {"topic": "agent speed"})
        finally:
            github.top_repos, github._gh = orig_top, orig_gh
        self.assertIn("code reusable with credit", out)
        self.assertIn("ideas only", out)
        rows = [t for _, t in ag.memory.recent()]
        self.assertTrue(any("licence MIT" in t for t in rows))


class AppServer(unittest.TestCase):
    def test_serves_ui_same_origin_with_security_headers(self):
        ui = Path(tempfile.mkdtemp())
        (ui / "index.html").write_text("<html>VAELON</html>")
        (ui / "_next").mkdir()
        (ui / "_next" / "app.js").write_text("console.log(1)")
        os.environ["VAELON_UI_DIR"] = str(ui)
        try:
            srv = server.serve(Config(provider="mock"), port=0)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            port = srv.server_address[1]
            r = urllib.request.urlopen(f"http://127.0.0.1:{port}/")
            self.assertIn("VAELON", r.read().decode())
            self.assertIn("frame-ancestors 'none'", r.headers["Content-Security-Policy"])
            js = urllib.request.urlopen(f"http://127.0.0.1:{port}/_next/app.js")
            self.assertEqual(js.headers["Content-Type"], "application/javascript")
            for bad in ("/../pyproject.toml", "/%2e%2e/%2e%2e/secret"):
                with self.assertRaises(urllib.error.HTTPError):
                    urllib.request.urlopen(f"http://127.0.0.1:{port}{bad}")
            self.assertTrue(json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/health"))["ok"])
            srv.shutdown()
            srv.server_close()
        finally:
            del os.environ["VAELON_UI_DIR"]


if __name__ == "__main__":
    unittest.main()
