"""The project name: data written by pre-release builds must keep working, and the old name must not come back."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["VAELON_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import vaelon  # noqa: E402
from vaelon import config  # noqa: E402
from vaelon.security import vault  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OLD = config.LEGACY_NAME


class DataFormat(unittest.TestCase):
    def test_format_constants_never_change(self):
        # these bytes are mixed into every key and every encrypted record of every existing installation
        self.assertEqual(vault.AAD.hex(), "756c74726f6e2d7631")
        self.assertEqual(vault.ENTROPY.hex(), "554c54524f4e2d7661756c742d76327c7365616c65642d73656372657473")
        self.assertEqual(vault.HKDF_SALT.hex(), "756c74726f6e2d686b64662d73616c74")
        self.assertEqual(vault.PREFIX, "enc1:")

    def test_text_encrypted_before_and_after_is_the_same_format(self):
        secret = vault.encrypt_text("Здравей, Vaelon")
        self.assertTrue(secret.startswith("enc1:"))
        self.assertEqual(vault.decrypt_text(secret), "Здравей, Vaelon")


class OldData(unittest.TestCase):
    def setUp(self):
        self.fake_home = Path(tempfile.mkdtemp())
        self.real_home = Path.home
        Path.home = staticmethod(lambda: self.fake_home)
        self.saved = {k: os.environ.pop(k, None) for k in ("VAELON_HOME", OLD.upper() + "_HOME")}

    def tearDown(self):
        Path.home = self.real_home
        for k, v in self.saved.items():
            if v is not None:
                os.environ[k] = v

    def test_old_folder_is_moved_once_and_intact(self):
        old = self.fake_home / ("." + OLD)
        (old / "secrets").mkdir(parents=True)
        (old / "secrets" / "master.key").write_bytes(b"\x01\x02\x03")
        (old / "config.json").write_text('{"address_as": "Boss"}', "utf-8")
        home = config._home()
        self.assertEqual(home, self.fake_home / ".vaelon")
        self.assertFalse(old.exists())
        self.assertEqual((home / "secrets" / "master.key").read_bytes(), b"\x01\x02\x03")
        self.assertEqual(config._home(), home)  # second start: nothing to move

    def test_new_folder_wins_and_old_one_is_left_alone(self):
        (self.fake_home / ".vaelon").mkdir()
        old = self.fake_home / ("." + OLD)
        old.mkdir()
        self.assertEqual(config._home(), self.fake_home / ".vaelon")
        self.assertTrue(old.exists())

    def test_fresh_install_and_explicit_folders(self):
        self.assertEqual(config._home(), self.fake_home / ".vaelon")
        os.environ[OLD.upper() + "_HOME"] = str(self.fake_home / "legacy")
        self.assertEqual(config._home(), self.fake_home / "legacy")
        os.environ["VAELON_HOME"] = str(self.fake_home / "mine")
        self.assertEqual(config._home(), self.fake_home / "mine")
        os.environ.pop("VAELON_HOME")
        os.environ.pop(OLD.upper() + "_HOME")


class OldSettings(unittest.TestCase):
    def test_key_stored_under_the_old_name_still_works(self):
        name = OLD.upper() + "_SMTP_PASS"
        os.environ[name] = "app-password-from-before"
        try:
            self.assertEqual(config.env("VAELON_SMTP_PASS"), "app-password-from-before")
            os.environ["VAELON_SMTP_PASS"] = "new-one"
            self.assertEqual(config.env("VAELON_SMTP_PASS"), "new-one")
        finally:
            os.environ.pop(name, None)
            os.environ.pop("VAELON_SMTP_PASS", None)
        self.assertEqual(config.env("VAELON_NOT_SET_ANYWHERE"), "")

    def test_saved_wake_word_and_voice_preset_follow_the_name(self):
        config.HOME.mkdir(parents=True, exist_ok=True)
        config.Config.path().write_text('{"wake_word": "%s", "voice": {"preset": "%s", "pitch": 0.8}}' % (OLD, OLD), "utf-8")
        try:
            cfg = config.Config.load()
            self.assertEqual(cfg.wake_word, "vaelon")
            self.assertEqual(cfg.voice, {"preset": "vaelon", "pitch": 0.8})
            from vaelon import tts

            self.assertEqual(tts.normalize(cfg.voice)["pitch"], 0.8)  # the owner's own slider values survive
        finally:
            config.Config.path().unlink()
        self.assertEqual(config.Config().wake_word, "vaelon")


class Name(unittest.TestCase):
    ALLOWED = ("AbuZar-Ansarii/Ultron", "modelscope/ultron", "sagar-builds/ultron", "MCU-Ultron persona",
               "OpenJarvis, Jarvis, Ultron and JARVIS projects")

    def test_the_product_says_vaelon(self):
        self.assertIn("Vaelon", vaelon.ABOUT)
        self.assertIn("Vaelon - originally created by", (ROOT / "NOTICE").read_text("utf-8"))
        self.assertIn("VAELON", (ROOT / "ui" / "web" / "app" / "layout.tsx").read_text("utf-8"))

    def test_the_old_name_is_gone_from_everything_that_ships(self):
        found = []
        places = [ROOT / "src", ROOT / "ui" / "web" / "app", ROOT / "ui" / "web" / "components", ROOT / "ui" / "web" / "lib",
                  ROOT / "docs", ROOT / "installer", ROOT / "scripts", ROOT / ".github"]
        files = [f for p in places for f in p.rglob("*") if f.is_file()]
        files += [ROOT / n for n in ("README.md", "NOTICE", "THIRD_PARTY.md", "pyproject.toml", "CHANGELOG.md",
                                    "PRIVACY.md", "SECURITY.md", "CONTRIBUTING.md")]
        for f in files:
            if any(part in ("webui", "__pycache__", "node_modules") for part in f.parts) or f.suffix in (".pyc", ".png"):
                continue
            try:
                text = f.read_text("utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for n, line in enumerate(text.splitlines(), 1):
                clean = line
                for ok in self.ALLOWED:
                    clean = clean.replace(ok, "")
                low = clean.lower()
                if OLD in low or "ултрон" in low:
                    if f.name == "config.py" and "LEGACY_NAME = " in line:
                        continue  # the one place the working title is kept, to find old data
                    found.append(f"{f.relative_to(ROOT).as_posix()}:{n}")
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
