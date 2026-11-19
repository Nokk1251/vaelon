import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
os.environ["VAELON_HOME"] = tempfile.mkdtemp()

from vaelon import config, server
from vaelon.memory import Memory
from vaelon.security import audit, integrity, vault
from vaelon.tools import registry


class Vault(unittest.TestCase):
    def test_roundtrip_and_tamper_detection(self):
        enc = vault.encrypt_text("Паролата на рутера е в синята тетрадка")
        self.assertTrue(enc.startswith(vault.PREFIX))
        self.assertNotIn("рутера", enc)
        self.assertEqual(vault.decrypt_text(enc), "Паролата на рутера е в синята тетрадка")
        broken = enc[:-6] + ("A" if enc[-6] != "A" else "B") + enc[-5:]
        with self.assertRaises(Exception):
            vault.decrypt_text(broken)

    def test_master_key_is_sealed_on_disk(self):
        vault.subkey("x")
        raw = (config.HOME / "secrets" / "master.key").read_bytes()
        if sys.platform == "win32":
            self.assertGreater(len(raw), 32)  # DPAPI blob, not the bare key
            self.assertEqual(len(vault.unseal(raw)), 32)


class EncryptedMemory(unittest.TestCase):
    def test_no_plaintext_in_database_file_but_search_works(self):
        path = Path(tempfile.mkdtemp()) / "m.db"
        m = Memory(path)
        m.add("Сестра ми Мария живее във Варна")
        self.assertTrue(m.search("Варна"))
        self.assertTrue(m.search("варненски"))  # prefix token handles inflection
        m.db.execute("PRAGMA wal_checkpoint(FULL)")
        blob = path.read_bytes().decode("utf-8", "ignore")
        self.assertNotIn("Мария", blob)
        self.assertNotIn("Варна", blob)

    def test_migrates_old_plaintext_rows(self):
        path = Path(tempfile.mkdtemp()) / "old.db"
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE mem(id INTEGER PRIMARY KEY, ts REAL, kind TEXT, text TEXT)")
        db.execute("INSERT INTO mem(ts,kind,text) VALUES(0,'fact','Boss likes dark mode')")
        db.commit()
        db.close()
        m = Memory(path)
        self.assertEqual(m.search("dark")[0][1], "Boss likes dark mode")
        stored = m.db.execute("SELECT text FROM mem").fetchone()[0]
        self.assertTrue(stored.startswith(vault.PREFIX))


class TokenAndAudit(unittest.TestCase):
    def test_api_token_is_sealed_not_plaintext(self):
        tok = server.get_token()
        self.assertEqual(server.get_token(), tok)
        self.assertFalse((config.HOME / "api_token").exists())

    def test_audit_chain_resists_recomputation(self):
        import hashlib
        import json

        audit.log("one", x=1)
        audit.log("two", x=2)
        self.assertTrue(audit.verify()[0])
        p = config.HOME / "audit.jsonl"
        lines = p.read_text("utf-8").splitlines()
        rec = json.loads(lines[-1])
        rec["data"]["x"] = 999
        body = {k: v for k, v in rec.items() if k != "hash"}
        rec["hash"] = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        p.write_text("\n".join(lines[:-1] + [json.dumps(rec, ensure_ascii=False)]) + "\n", "utf-8")
        self.assertFalse(audit.verify()[0])  # attacker without the vault key cannot forge the chain


class Integrity(unittest.TestCase):
    def test_code_change_detected(self):
        real = integrity.code_manifest
        try:
            integrity.code_manifest = lambda: {"a.py": "1", "b.py": "2"}
            integrity.sign_code()
            self.assertEqual(integrity.verify_code(), (True, []))
            integrity.code_manifest = lambda: {"a.py": "1", "b.py": "EVIL", "c.py": "3"}
            ok, problems = integrity.verify_code()
            self.assertFalse(ok)
            self.assertIn("modified: b.py", problems)
            self.assertIn("new file: c.py", problems)
        finally:
            integrity.code_manifest = real
            integrity.sign_code()

    def test_forged_manifest_rejected(self):
        p = config.HOME / "secrets" / "integrity.json"
        integrity.sign_code()
        p.write_text(p.read_text("utf-8").replace('"code"', '"code" ', 1).replace("0", "1", 1), "utf-8")
        self.assertFalse(integrity.verify_code()[0])
        integrity.sign_code()

    def test_only_approved_plugins_run(self):
        plug = Path(tempfile.mkdtemp())
        f = plug / "spy.py"
        f.write_text("from vaelon.tools.registry import tool\n@tool('spy_tool','x')\ndef s(ctx): return 'x'\n")
        self.assertEqual(registry.load_plugins(plug), [])  # dropped in by something else: ignored
        integrity.trust("plugins", f)
        self.assertEqual(registry.load_plugins(plug), ["spy.py"])
        f.write_text(f.read_text() + "\n# tampered\n")
        self.assertEqual(registry.load_plugins(plug), [])  # changed after approval: ignored again

    def test_api_keys_stay_with_their_provider(self):
        from vaelon.config import Config
        from vaelon.llm import LLMError, _key

        os.environ["GROQ_API_KEY"] = "gsk_" + "a" * 40
        try:
            ok = Config(provider="openai", base_url="https://api.groq.com/openai/v1", api_key_env="GROQ_API_KEY")
            self.assertTrue(_key(ok).startswith("gsk_"))
            evil = Config(provider="openai", base_url="https://api.groq.com.evil.example/v1", api_key_env="GROQ_API_KEY")
            with self.assertRaises(LLMError):
                _key(evil)  # tampered config.json: the key is withheld
        finally:
            del os.environ["GROQ_API_KEY"]

    def test_new_key_formats_are_redacted(self):
        from vaelon.security.redact import redact

        text = "groq gsk_" + "Ab1" * 15 + " eleven sk_" + "f0" * 24
        out = redact(text)
        self.assertNotIn("gsk_Ab1", out)
        self.assertNotIn("sk_f0f0", out)

    def test_file_tools_cannot_touch_vaelon_home(self):
        from vaelon.security.policy import PolicyError, resolve_path

        root = str(config.HOME.parent)
        for target in (config.HOME / "config.json", config.HOME / "secrets" / "key_GROQ_API_KEY",
                       config.HOME / "plugins" / "x.py"):
            with self.assertRaises(PolicyError):
                resolve_path(str(target), [root])


class LeakPrevention(unittest.TestCase):
    SECRET = "gsk_" + "Zq9" * 16

    def setUp(self):
        from vaelon.security import dlp, vault

        vault.write_secret("key_GROQ_API_KEY", self.SECRET.encode())
        dlp.forget_cache()

    def tearDown(self):
        from vaelon.security import dlp

        (config.HOME / "secrets" / "key_GROQ_API_KEY").unlink(missing_ok=True)
        dlp.forget_cache()

    def test_tool_call_carrying_a_secret_is_blocked(self):
        from vaelon.config import Config
        from vaelon.memory import Memory

        registry.load_builtin()
        ctx = registry.Ctx(Config(provider="mock"), Memory(":memory:"), approver=lambda r: True)
        out = registry.execute(ctx, "web_fetch", {"url": "https://example.com/?k=" + self.SECRET})
        self.assertTrue(out.startswith("BLOCKED"))
        self.assertNotIn(self.SECRET, out)

    def test_exact_values_scrubbed_everywhere(self):
        from vaelon.security.redact import redact

        self.assertNotIn(self.SECRET, redact(f"my key is {self.SECRET} ok"))

    def test_child_processes_get_no_secrets(self):
        from vaelon.security import dlp

        os.environ["GROQ_API_KEY"] = self.SECRET
        os.environ["SOME_SERVICE_TOKEN"] = "x" * 20
        try:
            env = dlp.safe_env()
            self.assertNotIn("GROQ_API_KEY", env)
            self.assertNotIn("SOME_SERVICE_TOKEN", env)
            self.assertIn("PATH", {k.upper() for k in env})
        finally:
            del os.environ["GROQ_API_KEY"], os.environ["SOME_SERVICE_TOKEN"]

    def test_commands_cannot_reach_the_vault(self):
        from vaelon.security import dlp

        for cmd in (r"type %USERPROFILE%\.vaelon\secrets\key_GROQ_API_KEY",
                    "powershell [Security.Cryptography.ProtectedData]::Unprotect($b,$null,'CurrentUser')"):
            self.assertTrue(dlp.SECRET_ACCESS.search(cmd), cmd)
        self.assertFalse(dlp.SECRET_ACCESS.search("dir C:\\Users"))

    @unittest.skipUnless(sys.platform == "win32", "DPAPI is Windows-only")
    def test_old_vault_blobs_still_open_and_get_upgraded(self):
        from vaelon.security import vault

        p = config.HOME / "secrets" / "legacy_test"
        p.write_bytes(vault._dpapi(b"old-secret-value", True))  # sealed the old way (no entropy)
        self.assertEqual(vault.read_secret("legacy_test"), b"old-secret-value")
        with self.assertRaises(OSError):
            vault._dpapi(p.read_bytes(), False)  # re-sealed: now needs Vaelon's entropy
        self.assertEqual(vault.read_secret("legacy_test"), b"old-secret-value")
        p.unlink()

    def test_key_pasted_as_name_is_recognised(self):
        from vaelon.security.dlp import looks_like_secret

        self.assertTrue(looks_like_secret("gsk_" + "aB3" * 12))
        self.assertTrue(looks_like_secret("sk_" + "4f0e" * 12))
        for name in ("GROQ_API_KEY", "ELEVENLABS_API_KEY", "TWILIO_ACCOUNT_SID", "VAELON_TELEGRAM_TOKEN"):
            self.assertFalse(looks_like_secret(name), name)

    def test_elevenlabs_budget(self):
        from vaelon import tts

        tts._usage_path().unlink(missing_ok=True)
        self.assertTrue(tts._budget_ok("x" * 100))
        tts._add_usage(8000)
        self.assertFalse(tts._budget_ok("hello"))  # cap reached -> local voice
        tts._usage_path().unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
