"""The holes found by attacking Vaelon on purpose (2026-11-16), each kept closed by a test. Offline: a temporary data
folder, servers only on 127.0.0.1, made-up files."""
import asyncio
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ["VAELON_HOME"] = tempfile.mkdtemp()
OUT = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vaelon import desktop, live, server  # noqa: E402
from vaelon.config import Config  # noqa: E402
from vaelon.security import policy, proof  # noqa: E402

BS = "\\"


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Paths(unittest.TestCase):
    def test_streams_devices_and_shares_are_refused(self):
        for p in ("C:" + BS + "a" + BS + "b.txt::$DATA", "C:" + BS + "a" + BS + "b.txt:hidden.exe", BS * 2 + "srv" + BS + "share" + BS + "x",
                  "//srv/share/x", BS * 2 + "?" + BS + "C:" + BS + "x", BS * 2 + "." + BS + "PhysicalDrive0", "C:" + BS + "a" + BS + "CON.txt",
                  "C:" + BS + "a" + BS + "com1", "C:" + BS + "a" + BS + "nul", "a\nb.txt"):
            self.assertTrue(policy.odd_path(p), p)
            with self.assertRaises(policy.PolicyError):
                policy.resolve_path(p, [OUT])
        for p in ("C:" + BS + "Users" + BS + "x" + BS + "report.pdf", "~/Documents/a.txt", "C:" + BS + "a" + BS + "console.txt"):
            self.assertFalse(policy.odd_path(p), p)

    def test_open_and_file_refuse_a_stream_of_a_file_in_the_output_folder(self):
        cfg = Config(output_dir=OUT)
        f = Path(OUT) / "ok.txt"
        f.write_text("fine", "utf-8")
        self.assertFalse(server.open_created(cfg, str(f) + "::$DATA", launch=lambda p, r: None)[0])
        self.assertTrue(server.open_created(cfg, str(f), launch=lambda p, r: None)[0])


class Port(unittest.TestCase):
    def test_nobody_else_can_bind_the_api_port(self):
        srv = server._Server(("127.0.0.1", 0), BaseHTTPRequestHandler)
        port = srv.server_address[1]
        try:
            s = socket.socket()
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            with self.assertRaises(OSError):
                s.bind(("127.0.0.1", port))
            s.close()
        finally:
            srv.server_close()

    def test_the_app_does_not_hand_its_key_to_a_stranger_on_its_port(self):
        seen = []

        class Fake(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                seen.append(self.path + " " + str(self.headers))
                body = json.dumps({"ok": True, "proof": "0" * 64}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        fake = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=fake.serve_forever, daemon=True).start()
        try:
            with self.assertRaises(desktop.PortTaken):
                desktop._core_running(fake.server_address[1])
            token = server.get_token()
            self.assertTrue(seen and not any(token in s for s in seen))  # the key was never sent
        finally:
            fake.shutdown()

    def test_the_real_core_proves_itself(self):
        port = free_port()
        srv = server.serve(Config(provider="mock", output_dir=OUT, allowed_roots=[OUT]), port=port)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            self.assertTrue(desktop._core_running(port))
            n = proof.nonce()
            got = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/hello?n={n}", timeout=5).read())["proof"]
            self.assertTrue(proof.check(server.get_token(), "vaelon-core", n, got))
            self.assertNotIn(server.get_token(), got)
            # a foreign web page is refused on every route, even with the key; a bad length is a 400, not a crash
            req = urllib.request.Request(f"http://127.0.0.1:{port}/jobs", headers={
                "Authorization": "Bearer " + server.get_token(), "Origin": "https://evil.example"})
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(e.exception.code, 403)
            s = socket.create_connection(("127.0.0.1", port), 5)
            s.sendall(f"POST /chat HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer {server.get_token()}\r\n"
                      f"Content-Length: abc\r\n\r\n".encode())
            self.assertIn(b" 400 ", s.recv(200))
            s.close()
        finally:
            srv.shutdown()
            srv.server_close()


@unittest.skipIf(live.websockets is None, "websockets is not installed")
class LiveHandshake(unittest.TestCase):
    def test_the_key_never_crosses_the_socket(self):
        port = live.start(server.Service(Config(provider="mock")), server.get_token(), free_port())
        self.assertTrue(port)
        token = server.get_token()

        async def talk(good: bool):
            import websockets

            async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
                n = proof.nonce()
                await ws.send(json.dumps({"hello": n}))
                c = json.loads(await ws.recv())
                self.assertEqual(c["type"], "challenge")
                self.assertTrue(proof.check(token, "vaelon-live-server", n, c["proof"]))
                self.assertNotIn(token, json.dumps(c))
                await ws.send(json.dumps({"proof": proof.proof(token, "vaelon-live-client", c["nonce"]) if good else "f" * 64}))
                try:
                    return json.loads(await ws.recv())
                except websockets.ConnectionClosed as e:
                    return {"closed": e.rcvd.code if e.rcvd else None}

        ok = asyncio.run(talk(True))
        self.assertEqual(ok.get("type"), "error")  # past the handshake: no Gemini key in this test
        self.assertEqual(asyncio.run(talk(False)), {"closed": 4401})

        async def old_style():  # the old way (sending the key) no longer opens anything
            import websockets

            async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
                await ws.send(json.dumps({"token": token}))
                try:
                    await ws.recv()
                except websockets.ConnectionClosed as e:
                    return e.rcvd.code if e.rcvd else None
        self.assertEqual(asyncio.run(old_style()), 4401)


if __name__ == "__main__":
    unittest.main()
