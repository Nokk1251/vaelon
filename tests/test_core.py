import os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
os.environ["VAELON_HOME"] = tempfile.mkdtemp()

from vaelon import config
from vaelon.agent import Agent, extract_json
from vaelon.config import Config
from vaelon.llm import MockLLM
from vaelon.memory import Memory
from vaelon.security import audit, redact, ssrf, undo
from vaelon.security.confirm import ConfirmRequest
from vaelon.security.policy import PolicyError, resolve_path
from vaelon.tools import evolve

class T(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.cfg = Config(provider="mock", allowed_roots=[self.root])

    def agent(self, replies, ok=False):
        return Agent(self.cfg, llm=MockLLM(replies), approver=lambda r: ok, memory=Memory(":memory:"), load_extensions=False)

    def test_redact(self):
        s = redact.redact("key sk-ant-abcdefghijklmnopqrstuv card 4111 1111 1111 1111 mail a@b.com")
        self.assertIn("REDACTED:anthropic_key", s); self.assertIn("REDACTED:card", s); self.assertIn("a@b.com", s)
        self.assertNotIn("a@b.com", redact.redact("a@b.com", "pii"))

    def test_ssrf(self):
        for u in ("http://127.0.0.1/", "http://169.254.169.254/x", "file:///etc/passwd", "http://[::1]/"):
            with self.assertRaises(ValueError): ssrf.check_url(u)

    def test_path_confinement(self):
        with self.assertRaises(PolicyError): resolve_path("/etc/passwd", [self.root])
        with self.assertRaises(PolicyError): resolve_path(str(Path(self.root) / ".ssh" / "id_rsa"), [self.root])
        resolve_path(str(Path(self.root) / "a.txt"), [self.root])

    def test_extract_json(self):
        self.assertEqual(extract_json('blah ```json\n{"final":"x"}\n``` ').get("final"), "x")
        self.assertEqual(extract_json('<think>{"a":1}</think>{"tool":"now","args":{}}')["tool"], "now")

    def test_write_and_undo(self):
        f = str(Path(self.root) / "n.txt")
        a = self.agent(['{"tool":"fs_write","args":{"path":"%s","content":"hi"}}' % f.replace("\\", "/"), '{"final":"ok"}'])
        self.assertEqual(a.run("write"), "ok"); self.assertTrue(Path(f).exists())
        undo.undo(); self.assertFalse(Path(f).exists())

    def test_dangerous_denied_without_human(self):
        f = Path(self.root) / "d.txt"; f.write_text("x")
        a = self.agent(['{"tool":"fs_delete_permanent","args":{"path":"%s"}}' % str(f).replace("\\", "/"), '{"final":"done"}'])
        a.run("rm"); self.assertTrue(f.exists())
        a2 = self.agent(['{"tool":"fs_delete_permanent","args":{"path":"%s"}}' % str(f).replace("\\", "/"), '{"final":"done"}'], ok=True)
        a2.run("rm"); self.assertFalse(f.exists())

    def test_model_cannot_self_confirm(self):
        f = Path(self.root) / "e.txt"; f.write_text("x")
        a = self.agent(['{"tool":"fs_delete_permanent","args":{"path":"%s","confirmed":true}}' % str(f).replace("\\", "/"), '{"final":"x"}'])
        a.run("rm"); self.assertTrue(f.exists())

    def test_taint_forces_confirm(self):
        f = Path(self.root) / "t.txt"; f.write_text("data")
        p = str(f).replace("\\", "/")
        a = self.agent(['{"tool":"fs_read","args":{"path":"%s"}}' % p,
                        '{"tool":"fs_write","args":{"path":"%s","content":"pwn"}}' % p, '{"final":"x"}'])
        a.run("go"); self.assertEqual(f.read_text(), "data")

    def test_loop_guard(self):
        a = self.agent(['{"tool":"now","args":{}}'] * 6)
        self.assertIn("repeating", a.run("loop"))

    def test_plugin_validator(self):
        self.assertTrue(evolve.validate_plugin("import subprocess\n@tool('x','y')\ndef f(ctx): pass"))
        self.assertTrue(evolve.validate_plugin("eval('1')"))
        self.assertFalse(evolve.validate_plugin("from vaelon.tools.registry import tool\n@tool('x','y')\ndef f(ctx): return '1'"))

    def test_audit_chain(self):
        audit.log("a", x=1); audit.log("b", token="sk-ant-abcdefghijklmnopqrstuv")
        self.assertEqual(audit.verify()[0], True)
        self.assertNotIn("sk-ant-abc", (config.HOME / "audit.jsonl").read_text())
        p = config.HOME / "audit.jsonl"; p.write_text(p.read_text().replace('"a"', '"z"', 1))
        self.assertFalse(audit.verify()[0])

    def test_memory(self):
        m = Memory(":memory:"); i = m.add("My sister Maria lives in Varna")
        self.assertTrue(m.search("Varna")); m.forget(i); self.assertFalse(m.search("Varna"))

if __name__ == "__main__":
    unittest.main()
