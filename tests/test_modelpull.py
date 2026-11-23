"""Downloading the local model from the app (modelpull): against a stand-in Ollama on 127.0.0.1 that streams progress
lines the way the real one does. Nothing is downloaded from anywhere."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ["VAELON_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vaelon import modelpull  # noqa: E402
from vaelon.config import Config  # noqa: E402
from vaelon.providers import PRESETS  # noqa: E402

SEEN: list = []


class FakeOllama(BaseHTTPRequestHandler):
    mode = "ok"
    gate = threading.Event()

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        SEEN.append((self.path, body))
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        lines = [{"status": "pulling manifest"}]
        if FakeOllama.mode == "error":
            lines.append({"error": "pull model manifest: file does not exist"})
        else:
            lines += [{"status": "pulling aaa", "digest": "sha256:aaa", "total": 2000, "completed": 500},
                      {"status": "pulling bbb", "digest": "sha256:bbb", "total": 1000, "completed": 1000},
                      {"status": "pulling aaa", "digest": "sha256:aaa", "total": 2000, "completed": 2000},
                      {"status": "verifying sha256 digest"}, {"status": "success"}]
        for i, line in enumerate(lines):
            if FakeOllama.mode == "slow" and i == 1:
                FakeOllama.gate.wait(5)
            self.wfile.write((json.dumps(line) + "\n").encode())
            self.wfile.flush()


def serve():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def wait_done(limit=5.0):
    end = time.time() + limit
    while modelpull.status()["running"] and time.time() < end:
        time.sleep(0.02)
    return modelpull.status()


class Pull(unittest.TestCase):
    def setUp(self):
        self.srv = serve()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        SEEN.clear()
        FakeOllama.mode = "ok"
        FakeOllama.gate.clear()
        wait_done()

    def tearDown(self):
        FakeOllama.gate.set()
        wait_done()
        self.srv.shutdown()

    def cfg(self, model="qwen3:4b-instruct"):
        return Config(provider="ollama", base_url=self.base, model=model)

    def test_progress_and_success(self):
        modelpull.start(self.cfg())
        s = wait_done()
        self.assertTrue(s["done"], s)
        self.assertEqual((s["error"], s["percent"], s["total"]), ("", 100.0, 3000))
        self.assertEqual(SEEN, [("/api/pull", {"model": "qwen3:4b-instruct", "stream": True})])

    def test_an_ollama_error_is_reported(self):
        FakeOllama.mode = "error"
        modelpull.start(self.cfg())
        s = wait_done()
        self.assertFalse(s["done"])
        self.assertIn("does not exist", s["error"])

    def test_one_download_at_a_time(self):
        FakeOllama.mode = "slow"
        first = modelpull.start(self.cfg())
        second = modelpull.start(self.cfg())
        self.assertTrue(first["running"] and second["running"])
        FakeOllama.gate.set()
        self.assertTrue(wait_done()["done"])
        self.assertEqual(len(SEEN), 1)  # the second request did not start another download

    def test_the_model_always_comes_from_the_settings(self):
        # a cloud provider is configured: the download is the local preset's model, on the default address
        self.assertEqual(modelpull._target(Config(provider="openai", model="gpt-x")),
                         ("http://localhost:11434", PRESETS["local"]["model"]))
        s = modelpull.start(self.cfg(model="evil model; rm -rf"))  # a bad name is refused before any request
        self.assertIn("not valid", s["error"])
        self.assertEqual(SEEN, [])

    def test_ollama_not_running(self):
        self.srv.shutdown()
        self.srv.server_close()
        modelpull.start(self.cfg())
        s = wait_done()
        self.assertEqual(s["error"], "Ollama is not answering")
        self.srv = serve()  # for tearDown


class Route(unittest.TestCase):
    def test_only_the_app_with_its_key_may_start_it(self):
        import urllib.error
        import urllib.request

        from vaelon import server

        svc = server.Service(Config(provider="mock"))
        token = server.get_token()
        httpd = server._Server(("127.0.0.1", 0), server.make_handler(svc, token, 0))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{httpd.server_address[1]}/ollama/pull"
        try:
            for headers, want in (({}, 401), ({"Authorization": f"Bearer {token}", "Origin": "https://evil.example"}, 403)):
                req = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json", **headers})
                with self.assertRaises(urllib.error.HTTPError) as e:
                    urllib.request.urlopen(req, timeout=5)
                self.assertEqual(e.exception.code, want)
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
            got = json.loads(urllib.request.urlopen(req, timeout=5).read())
            self.assertIn("percent", got)
        finally:
            httpd.shutdown()


if __name__ == "__main__":
    unittest.main()
