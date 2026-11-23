"""The local model picker: the curated list, the look at the computer, and the advice for each model - on made-up
computers (nothing here reads the real graphics card or downloads anything)."""
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

from vaelon import localmodels as L, modelpull, server  # noqa: E402
from vaelon.config import Config  # noqa: E402


def pc(memory, free, graphics=(), apple=False):
    return {"processor": "test CPU", "cores": 8, "graphics": list(graphics), "apple_silicon": apple,
            "memory_gb": memory, "free_gb": free}


def by_name(rows):
    return {r["name"]: r for r in rows}


class Advice(unittest.TestCase):
    def test_a_small_computer_gets_the_lightest_model(self):
        rows = by_name(L.assess(pc(6, 3), [], ""))
        self.assertTrue(rows["llama3.2:3b"]["recommended"])
        self.assertEqual(rows["gemma3:12b"]["fit"], "too_big")
        self.assertEqual(rows["llama3.2:3b"]["speed"], "usable")

    def test_a_laptop_without_a_graphics_card(self):  # 16 GB, little free, graphics built into the processor
        rows = by_name(L.assess(pc(16.4, 3.9, [{"name": "Radeon", "vram_gb": 0.5, "kind": "integrated"}]),
                                ["qwen3:4b-instruct"], "qwen3:4b-instruct"))
        r = rows["qwen3:4b-instruct"]
        self.assertTrue(r["recommended"] and r["installed"] and r["in_use"])
        self.assertEqual(r["fit"], "ok")  # loaded already: its own memory is not "taken" from it
        self.assertEqual(rows["gemma3:12b"]["speed"], "very_slow")

    def test_an_apple_silicon_mac_runs_the_big_one_fast(self):
        rows = by_name(L.assess(pc(24, 18, [{"name": "Apple", "vram_gb": 0, "kind": "apple"}], apple=True), [], ""))
        self.assertTrue(rows["gemma3:12b"]["recommended"])
        self.assertEqual(rows["gemma3:12b"]["speed"], "fast")

    def test_a_graphics_card_with_8_gb(self):
        rows = by_name(L.assess(pc(32, 20, [{"name": "NVIDIA RTX", "vram_gb": 8.0, "kind": "nvidia"}]), [], ""))
        self.assertTrue(rows["qwen2.5:7b"]["recommended"])
        self.assertEqual(rows["qwen2.5:7b"]["speed"], "fast")  # 6.2 GB need fits the card
        self.assertEqual(rows["gemma3:12b"]["speed"], "very_slow")  # 9.7 GB does not

    def test_exactly_one_recommendation_and_installed_models_are_seen(self):
        rows = L.assess(pc(16, 8), ["gemma3:4b", "something-else:latest"], "")
        self.assertEqual(sum(r["recommended"] for r in rows), 1)
        self.assertTrue(by_name(rows)["gemma3:4b"]["installed"])
        self.assertFalse(by_name(rows)["qwen2.5:7b"]["installed"])

    def test_the_model_in_use_is_not_told_to_close_other_programs(self):  # its own memory counts as taken
        rows = by_name(L.assess(pc(16.4, 2.3), ["qwen3:4b-instruct"], "qwen3:4b-instruct"))
        self.assertEqual(rows["qwen3:4b-instruct"]["fit"], "ok")
        self.assertEqual(rows["gemma3:4b"]["fit"], "tight")  # a second model still needs free memory

    def test_nothing_that_cannot_run_is_recommended(self):
        rows = L.assess(pc(3, 1), [], "")
        self.assertEqual(sum(r["recommended"] for r in rows), 0)

    def test_a_small_processor_makes_it_one_step_slower(self):
        rows = by_name(L.assess({**pc(16, 10), "cores": 2}, [], ""))
        self.assertEqual(rows["qwen3:4b-instruct"]["speed"], "slow")
        self.assertEqual(rows["gemma3:4b"]["speed"], "very_slow")

    def test_the_list_holds_no_thinking_models_and_only_valid_names(self):
        self.assertFalse({"qwen3:4b", "qwen3:8b", "qwen3:1.7b"} & L.NAMES)
        for m in L.CATALOG:
            self.assertTrue(modelpull.NAME_RX.match(m["name"]), m["name"])
            self.assertGreater(m["size_gb"], 0)


class Computer(unittest.TestCase):
    def setUp(self):
        self.real = (L._run, sys.platform)

    def tearDown(self):
        L._run, sys.platform = self.real
        L._cache.update(machine=None)

    def test_graphics_on_windows_from_nvidia_smi_and_the_system(self):
        def fake(args, timeout=8):
            if args[0] == "nvidia-smi":
                return "NVIDIA GeForce RTX 3060, 12288\n"
            if "Win32_VideoController" in " ".join(args):
                return json.dumps([{"Name": "NVIDIA GeForce RTX 3060", "AdapterRAM": 4293918720},
                                   {"Name": "Intel(R) UHD Graphics 630", "AdapterRAM": 1073741824}])
            return ""
        L._run = fake
        sys.platform = "win32"
        g = L._graphics()
        self.assertEqual(g[0], {"name": "NVIDIA GeForce RTX 3060", "vram_gb": 12.0, "kind": "nvidia"})
        self.assertEqual(g[1]["kind"], "integrated")
        self.assertEqual(len(g), 2)  # the card is not listed twice

    def test_graphics_built_into_a_ryzen_processor_are_not_a_graphics_card(self):
        rows = [{"Name": "AMD Radeon(TM) Graphics", "AdapterRAM": 2147483648},
                {"Name": "AMD Radeon 780M Graphics", "AdapterRAM": 4293918720},
                {"Name": "AMD Radeon RX 6700 XT", "AdapterRAM": 4293918720},
                {"Name": "Odd adapter", "AdapterRAM": "not a number"}]
        L._run = lambda args, timeout=8: json.dumps(rows) if "Win32_VideoController" in " ".join(args) else ""
        sys.platform = "win32"
        kinds = {g["name"]: g["kind"] for g in L._graphics()}
        self.assertEqual(kinds["AMD Radeon(TM) Graphics"], "integrated")
        self.assertEqual(kinds["AMD Radeon 780M Graphics"], "integrated")
        self.assertEqual(kinds["AMD Radeon RX 6700 XT"], "amd")
        self.assertEqual(kinds["Odd adapter"], "other")  # a text where a number belongs does not break the list

    def test_graphics_never_fail(self):
        def broken(args, timeout=8):
            raise RuntimeError("unexpected")
        L._run = broken
        sys.platform = "win32"  # an Apple silicon Mac answers without asking any program (see the next test)
        self.assertEqual(L._graphics(), [])

    def test_an_apple_silicon_mac_needs_no_program_to_tell(self):
        L._run = lambda args, timeout=8: self.fail("no program should be asked on Apple silicon")
        real = L.platform.machine
        sys.platform, L.platform.machine = "darwin", lambda: "arm64"
        try:
            self.assertEqual([g["kind"] for g in L._graphics()], ["apple"])
        finally:
            L.platform.machine = real

    def test_output_that_is_not_utf8_does_not_break_the_look(self):  # e.g. a console code page on Windows
        L._run = self.real[0]
        out = L._run([sys.executable, "-c", "import sys; sys.stdout.buffer.write(bytes([0x98, 0xff]) + b'ok')"])
        self.assertTrue(out.endswith("ok"))

    def test_processor_and_graphics_are_read_once(self):
        calls = []
        L._run = lambda args, timeout=8: calls.append(args) or ""
        L.machine(refresh=True)
        n = len(calls)
        L.machine()
        L.machine()
        self.assertEqual(len(calls), n)

    def test_machine_never_fails_without_tools(self):
        L._run = lambda args, timeout=8: ""
        m = L.machine(refresh=True)
        self.assertEqual(set(m) >= {"memory_gb", "free_gb", "processor", "graphics", "cores"}, True)


class Choice(unittest.TestCase):
    def test_only_models_from_the_list_can_be_downloaded(self):
        s = modelpull.start(Config(provider="ollama", base_url="http://127.0.0.1:9"), "evil/model:huge")
        self.assertIn("not in Vaelon's list", s["error"])
        self.assertFalse(s["running"])
        base, model = modelpull._target(Config(provider="ollama", model="qwen3:4b-instruct"), "gemma3:4b")
        self.assertEqual(model, "gemma3:4b")
        self.assertEqual(modelpull._target(Config(provider="ollama", model="qwen3:4b-instruct"), "not-listed")[1],
                         "qwen3:4b-instruct")


class Route(unittest.TestCase):
    def setUp(self):  # never run the real PowerShell / nvidia-smi here: a made-up computer
        self.real = L._run
        L._run = lambda args, timeout=8: ""
        L._cache.update(machine=None)
        self.started = []
        self.real_pull = modelpull._pull
        modelpull._pull = lambda *a: self.started.append(a)

    def tearDown(self):
        L._run = self.real
        L._cache.update(machine=None)
        modelpull._pull = self.real_pull

    def serve(self, cfg):
        token = server.get_token()
        httpd = server._Server(("127.0.0.1", 0), server.make_handler(server.Service(cfg), token, 0))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        base = f"http://127.0.0.1:{httpd.server_address[1]}"

        def call(path, body=None):
            req = urllib.request.Request(base + path, headers={"Authorization": f"Bearer {token}"},
                                         data=json.dumps(body).encode() if body is not None else None,
                                         method="POST" if body is not None else "GET")
            return json.loads(urllib.request.urlopen(req, timeout=20).read())
        return base, call

    def test_the_picker_route_needs_the_key_and_lists_the_models(self):
        base, call = self.serve(Config(provider="ollama", base_url="http://127.0.0.1:9"))  # an Ollama that answers nothing
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base + "/models/local", timeout=10)
        self.assertEqual(e.exception.code, 401)
        got = call("/models/local")
        self.assertEqual([m["name"] for m in got["models"]], [m["name"] for m in L.CATALOG])
        self.assertFalse(got["ollama"]["reachable"])
        self.assertFalse(got["remote"] or got["in_use_installed"])
        self.assertIn("memory_gb", got["machine"])

    def test_a_model_outside_the_list_in_use_is_seen_as_working(self):  # so a download never switches it silently
        from vaelon import settings
        real = settings.ollama
        settings.ollama = lambda cfg, *a, **k: {"reachable": True, "models": ["mistral:7b", "gemma3:4b"]}
        try:
            _, call = self.serve(Config(provider="ollama", model="mistral:7b"))
            got = call("/models/local")
        finally:
            settings.ollama = real
        self.assertEqual((got["in_use"], got["in_use_installed"]), ("mistral:7b", True))
        self.assertFalse(any(m["in_use"] for m in got["models"]))

    def test_ollama_on_another_computer_is_said(self):
        _, call = self.serve(Config(provider="ollama", base_url="http://192.168.1.20:11434"))
        self.assertTrue(call("/models/local")["remote"])

    def test_a_download_outside_the_list_is_refused_over_http(self):
        _, call = self.serve(Config(provider="ollama", model="qwen3:4b-instruct", base_url="http://127.0.0.1:9"))
        got = call("/ollama/pull", {"model": "evil/x:huge"})
        self.assertIn("not in Vaelon's list", got["error"])
        self.assertEqual(self.started, [])  # nothing was asked of Ollama
        self.assertEqual(call("/ollama/pull?model=evil")["model"], "qwen3:4b-instruct")


if __name__ == "__main__":
    unittest.main()
