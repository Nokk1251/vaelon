"""macOS code paths, checked on any system by simulating the Mac: the Keychain-wrapped vault, notifications and the
system voice called with argument lists (no text ever becomes a command), Mac-specific protected paths and auto-start
places. The real .app / .dmg is built and run on a Mac (scripts/build_mac.py)."""
import os
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from pathlib import Path

os.environ["VAELON_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vaelon import platform_mac  # noqa: E402
from vaelon.security import dlp, policy, vault  # noqa: E402


class FakeKeyring(types.ModuleType):
    def __init__(self):
        super().__init__("keyring")
        self.store = {}

    def get_password(self, service, account):
        return self.store.get((service, account))

    def set_password(self, service, account, value):
        self.store[(service, account)] = value


@contextmanager
def mac():
    real, kr = sys.platform, FakeKeyring()
    sys.modules["keyring"] = kr
    sys.platform = "darwin"
    try:
        yield kr
    finally:
        sys.platform = real
        sys.modules.pop("keyring", None)


class Vault(unittest.TestCase):
    def test_secrets_are_sealed_with_the_keychain_key(self):
        with mac() as kr:
            blob = vault.seal(b"gsk_secret_value")
            self.assertTrue(blob.startswith(b"mk1:"))
            self.assertNotIn(b"gsk_secret_value", blob)
            self.assertEqual(vault.unseal(blob), b"gsk_secret_value")
            self.assertEqual(len(kr.store), 1)  # one wrapping key, held by the Keychain - not in ~/.vaelon
            kr.store.clear()  # a copy of ~/.vaelon on another Mac: no Keychain item there
            with self.assertRaises(OSError):
                vault.unseal(blob)
            with self.assertRaises(OSError):
                vault.unseal(b"plain text planted in the file")

    def test_missing_keyring_says_what_to_install(self):
        real = sys.platform
        sys.modules["keyring"] = None  # "not installed": import raises ImportError
        sys.platform = "darwin"
        try:
            with self.assertRaises(OSError) as e:
                vault.seal(b"x")
            self.assertIn("pip install keyring", str(e.exception))
        finally:
            sys.platform = real
            sys.modules.pop("keyring", None)

    def test_keyring_is_a_base_dependency_on_macos(self):
        try:
            import tomllib  # Python 3.11+
        except ImportError:
            self.skipTest("tomllib needs Python 3.11")

        deps = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text("utf-8"))["project"]["dependencies"]
        self.assertTrue(any(d.startswith("keyring") and "darwin" in d for d in deps))

    def test_write_and_read_a_secret_on_a_mac(self):
        with mac():
            vault.write_secret("key_TEST", b"value-123")
            raw = (Path(os.environ["VAELON_HOME"]) / "secrets" / "key_TEST").read_bytes()
            self.assertNotIn(b"value-123", raw)
            self.assertEqual(vault.read_secret("key_TEST"), b"value-123")


class Commands(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.real_run = platform_mac.subprocess.run

        def fake_run(args, **kw):
            self.calls.append(args)
            out = Path(args[args.index("-o") + 1]) if "-o" in args else None
            if out:
                out.write_bytes(b"RIFF....WAVEfmt ")
            return types.SimpleNamespace(returncode=0, stdout="Alex  en_US  # hi\nDaria  bg_BG  # hi\n", stderr=b"")
        platform_mac.subprocess.run = fake_run

    def tearDown(self):
        platform_mac.subprocess.run = self.real_run

    def test_notification_text_is_an_argument_not_script(self):
        evil = 'x" & do shell script "rm -rf ~" & "'
        platform_mac.notify("Vaelon", evil)
        args = self.calls[-1]
        self.assertEqual(args[0], "osascript")
        scripts = [args[i + 1] for i, a in enumerate(args) if a == "-e"]
        self.assertFalse(any(evil in s for s in scripts))  # the words never enter the AppleScript source
        self.assertEqual(args[-1], evil[:300])

    def test_system_voice_reads_text_from_a_file(self):
        platform_mac.say("Hello; rm -rf ~", "bg")
        args = self.calls[-1]
        self.assertEqual(args[0], "say")
        self.assertIn("-f", args)
        self.assertNotIn("Hello; rm -rf ~", " ".join(args))
        self.assertIn("Daria", args)  # the Bulgarian voice for "bg"


class Paths(unittest.TestCase):
    def test_mac_private_places_are_protected(self):
        home = Path(tempfile.mkdtemp())
        for rel in ("Library/Keychains/login.keychain-db", "Library/Cookies/Cookies.binarycookies", ".zsh_history",
                    "Library/Application Support/Google/Chrome/Default/Login Data"):
            p = home / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x", "utf-8")
            with self.assertRaises(policy.PolicyError, msg=rel):
                policy.resolve_path(str(p), [str(home)])

    def test_mac_auto_start_places_ask_first(self):
        for p in ("/Users/x/Library/LaunchAgents/com.evil.plist", "/Users/x/.zshrc", "/Users/x/run.command",
                  "/Users/x/Library/LaunchAgents"):
            self.assertTrue(policy.runs_by_itself(p), p)
        self.assertFalse(policy.runs_by_itself("/Users/x/Documents/notes.txt"))

    def test_every_login_shell_file_asks(self):  # red team R-01: .zlogin & co. were written without a card
        for rel in (".zlogin", ".zlogout", ".bash_login", ".bash_logout", ".config/fish/config.fish",
                    ".config/fish/conf.d/x.fish", "Library/LaunchAgents/x.plist", "Desktop/x.command", "Desktop/x.terminal"):
            self.assertTrue(policy.runs_by_itself("/Users/x/" + rel), rel)
        self.assertFalse(policy.runs_by_itself("/Users/x/Documents/report.txt"))

    def test_uploads_and_downloads_get_the_quarantine_flag(self):
        from vaelon import guardian

        calls, real = [], guardian.subprocess.run
        guardian.subprocess.run = lambda args, **kw: calls.append(args)
        try:
            with mac():
                guardian.mark_from_internet("/Users/x/Downloads/report.docm")
        finally:
            guardian.subprocess.run = real
        self.assertEqual(calls[0][:3], ["xattr", "-w", "com.apple.quarantine"])
        self.assertEqual(calls[0][-1], "/Users/x/Downloads/report.docm")

    def test_commands_cannot_read_the_keychain(self):
        for cmd in ("security find-generic-password -s Vaelon -w", "security dump-keychain", "security export -k login.keychain"):
            self.assertTrue(dlp.SECRET_ACCESS.search(cmd), cmd)


class BuildScripts(unittest.TestCase):
    def test_build_scripts_import_and_share_their_helpers(self):  # `run` / `_has` were lost once (NameError at build)
        import importlib

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
        app = importlib.import_module("build_app")
        mac = importlib.import_module("build_mac")
        for name in ("run", "_has", "prune", "EXCLUDE", "PKG", "WEB"):
            self.assertTrue(hasattr(app, name), name)
        self.assertIs(mac.run, app.run)
        self.assertTrue(app._has("json"))
        self.assertFalse(app._has("no_such_module_vaelon"))
        root = Path(tempfile.mkdtemp())  # a pruned bundle: a link whose target was deleted must go, a good one stays
        (root / "Resources").mkdir()
        (root / "Resources" / "kept.txt").write_text("x", "utf-8")
        try:
            (root / "good").symlink_to(root / "Resources" / "kept.txt")
            (root / "bad").symlink_to(root / "Resources" / "deleted.txt")
        except OSError:
            self.skipTest("this system does not allow symbolic links for this user")
        self.assertEqual(mac.drop_broken_links(root), ["bad"])
        self.assertTrue((root / "good").exists())


if __name__ == "__main__":
    unittest.main()
