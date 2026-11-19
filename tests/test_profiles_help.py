"""Profiles (optional focus) and the Help page's feedback note. Offline, temporary data and output folders."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["VAELON_HOME"] = tempfile.mkdtemp()
OUT = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vaelon import catalog, feedback, focus, router, settings  # noqa: E402
from vaelon.agent import Agent  # noqa: E402
from vaelon.config import Config  # noqa: E402
from vaelon.tools import registry  # noqa: E402

registry.load_builtin()


class Profiles(unittest.TestCase):
    def cfg(self, *names):
        return Config(provider="mock", output_dir=OUT, profiles=list(names))

    def test_every_starter_tool_exists(self):
        for name, p in focus.PROFILES.items():
            for tool in p["starter"]:
                self.assertIn(tool, registry.REGISTRY, f"{name}: {tool}")
            self.assertTrue(p["title"] and p["blurb"] and p["hint"])

    def test_no_profile_changes_nothing(self):
        self.assertEqual(router.route("hello", self.cfg()), router.route("hello"))
        self.assertEqual(focus.hint(self.cfg()), "")
        self.assertEqual(list(focus.order_examples(catalog.EXAMPLES, self.cfg())), list(catalog.EXAMPLES))

    def test_a_profile_adds_its_tools_and_keeps_the_rest(self):
        plain = router.route("hello")
        biz = router.route("hello", self.cfg("business"))
        self.assertTrue(plain < biz)
        self.assertIn("bill_add", biz)
        self.assertNotIn("bill_add", plain)
        # keyword groups still work on top of a profile, and the toolbox is the same turn after turn (prompt cache)
        self.assertIn("create_presentation", router.route("make a presentation", self.cfg("business")))
        self.assertEqual(router.route("hi", self.cfg("business", "coding")), router.route("hey", self.cfg("coding", "business")))

    def test_order_and_hint(self):
        cfg = self.cfg("coding", "business")  # stored order does not matter
        self.assertEqual(focus.chosen(cfg), ["business", "coding"])
        self.assertTrue(focus.hint(cfg).startswith("USER FOCUS: The user runs a business"))
        first = list(focus.order_examples(catalog.EXAMPLES, cfg))
        self.assertEqual(first[:2], ["Bills and invoices", "Budget"])
        self.assertEqual(sorted(first), sorted(catalog.EXAMPLES))  # nothing lost, nothing doubled

    def test_the_hint_goes_into_the_request_not_the_cached_prompt(self):
        a = Agent(self.cfg("learning"), load_extensions=False)
        self.assertIn("USER FOCUS", a._context("explain photosynthesis"))
        self.assertNotIn("USER FOCUS", a._system(None, router.route("", a.cfg)))
        twin = a.fork()
        twin.work_only = True  # someone else's work mode in company mode never gets the owner's focus
        self.assertNotIn("USER FOCUS", twin._context("explain photosynthesis"))

    def test_settings_accept_only_known_profiles(self):
        cfg = self.cfg()
        changed, problem = settings.apply(cfg, {"profiles": ["learning", "life", "learning"]})
        self.assertEqual((changed, problem), (["profiles"], None))
        self.assertEqual(cfg.profiles, ["learning", "life"])
        for bad in (["admin"], "business", [1], ["business"] * 9, None):
            self.assertIsNotNone(settings.apply(cfg, {"profiles": bad})[1], bad)
        self.assertEqual(cfg.profiles, ["learning", "life"])
        self.assertEqual(settings.apply(cfg, {"profiles": []}), (["profiles"], None))
        snap = settings.snapshot(cfg)
        self.assertEqual([p["name"] for p in snap["profiles"]], list(focus.PROFILES))
        self.assertIn("feedback_mail", snap)


class Feedback(unittest.TestCase):
    def test_saved_as_a_file_with_no_secrets(self):
        cfg = Config(provider="mock", output_dir=OUT)
        out = feedback.save(cfg, "problem", "The \x07 budget tab is slow.\nSteps: open it.")
        p = Path(out["path"])
        self.assertTrue(p.is_file() and p.parent == Path(OUT) / "Feedback")
        text = p.read_text("utf-8")
        self.assertIn("Vaelon feedback - problem", text)
        self.assertNotIn("\x07", text)
        self.assertIn("model: local", text)
        self.assertNotIn(str(Path.home()), text)
        self.assertEqual(out["mailto"], "")  # no feedback address published yet: nothing but the file
        second = feedback.save(cfg, "idea", "x")
        self.assertNotEqual(second["path"], out["path"])

    def test_bad_input(self):
        cfg = Config(provider="mock", output_dir=OUT)
        for kind, text in (("problem", ""), ("problem", "   "), ("problem", None), ("hack", "x"), ("idea", "x" * 5001)):
            with self.assertRaises(ValueError):
                feedback.save(cfg, kind, text)

    def test_a_stored_key_never_reaches_the_note(self):
        from vaelon.security import dlp, vault

        key = "gsk_" + "A1b2C3d4E5f6G7h8J9k0" * 2
        vault.write_secret("key_GROQ_API_KEY", key.encode())
        dlp.forget_cache()
        try:
            text = feedback.note(Config(provider="mock"), "problem", f"my key {key} does not work")
            self.assertNotIn(key, text)
        finally:
            (Path(os.environ["VAELON_HOME"]) / "secrets" / "key_GROQ_API_KEY").unlink(missing_ok=True)
            dlp.forget_cache()


if __name__ == "__main__":
    unittest.main()
