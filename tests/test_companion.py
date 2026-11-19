"""The floating companion: screen sharing consent, looking at the screen before answering, the window bridge.
Offline: the screen is never captured - the screen tool is replaced by a stub."""
import os
import sys
import tempfile
import unittest

os.environ["VAELON_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vaelon import desktop  # noqa: E402
from vaelon.agent import SCREEN_RX, Agent  # noqa: E402
from vaelon.config import Config  # noqa: E402
from vaelon.llm import MockLLM  # noqa: E402
from vaelon.memory import Memory  # noqa: E402
from vaelon.tools import registry  # noqa: E402


class Screen(unittest.TestCase):
    def setUp(self):
        registry.load_builtin()
        self.tool = registry.REGISTRY["see_screen"]
        self.original = self.tool.func
        self.looks = []
        self.tool.func = lambda ctx, question="": self.looks.append(question) or "an error box: ERROR 404 file not found"

    def tearDown(self):
        self.tool.func = self.original

    def agent(self, replies):
        a = Agent(Config(provider="mock"), llm=MockLLM(replies), memory=Memory(":memory:"), load_extensions=False)
        a.use_intents = False
        return a

    def test_without_the_switch_the_screen_needs_an_approval(self):
        asked = []
        ctx = registry.Ctx(Config(provider="mock"), approver=lambda req: asked.append(req.tool) or False)
        self.assertIn("DENIED", registry.execute(ctx, "see_screen", {}))
        self.assertEqual(asked, ["see_screen"])
        self.assertEqual(self.looks, [])

    def test_the_switch_is_the_consent_but_never_after_outside_content(self):
        asked = []
        ctx = registry.Ctx(Config(provider="mock"), approver=lambda req: asked.append(req.tool) or False,
                           extra={"screen_ok": True})
        self.assertIn("ERROR 404", registry.execute(ctx, "see_screen", {"question": "what is this"}))
        self.assertEqual(asked, [])  # no extra click: the user switched screen sharing on
        self.assertTrue(ctx.tainted)  # what is on a screen is outside content
        self.assertIn("DENIED", registry.execute(ctx, "see_screen", {}))  # second look in a tainted task: ask
        self.assertEqual(asked, ["see_screen"])
        # the switch covers this one tool only
        self.assertIn("DENIED", registry.execute(registry.Ctx(Config(provider="mock"), extra={"screen_ok": True}),
                                                 "fs_delete_permanent", {"path": "x"}))

    def test_a_question_about_the_screen_looks_first(self):
        a = self.agent(['{"final": "It says the file was not found."}'])
        events = []
        out = a.run("What does this error say?", screen=True, spoken=True, on_event=lambda k, d: events.append((k, d)))
        self.assertEqual(out, "It says the file was not found.")
        self.assertEqual(self.looks, ["What does this error say?"])
        self.assertIn(("tool", "see_screen"), events)
        prompt = "\n".join(m["content"] for m in a.llm.seen[0])
        self.assertIn("SCREEN SHARING IS ON", prompt)
        self.assertIn("ERROR 404", prompt)

    def test_other_questions_do_not_look_and_nothing_looks_when_sharing_is_off(self):
        a = self.agent(['{"final": "Why did the chicken..."}', '{"final": "I cannot see your screen."}'])
        a.run("Tell me a joke", screen=True)
        a.run("What does this error say?")  # sharing off
        self.assertEqual(self.looks, [])
        self.assertNotIn("SCREEN SHARING IS ON", a.llm.seen[1][-1]["content"])

    def test_words_that_point_at_the_screen(self):
        for text in ("what is on my screen", "explain this", "Какво пише тук?", "виж грешката", "what am I looking at"):
            self.assertTrue(SCREEN_RX.search(text), text)
        for text in ("tell me a joke", "колко е часът"):
            self.assertFalse(SCREEN_RX.search(text), text)


class FakeEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, fn):
        self.handlers.append(fn)
        return self

    def fire(self):
        for fn in self.handlers:
            fn()

    def fire_with(self, *args):
        for fn in self.handlers:
            fn(*args)


class FakeWindow:
    def __init__(self, **kw):
        self.kw, self.visible, self.destroyed = kw, True, False
        self.events = type("Events", (), {})()
        self.events.closed = FakeEvent()
        self.events.shown = FakeEvent()
        self.events.moved = FakeEvent()

    def hide(self):
        self.visible = False

    def show(self):
        self.visible = True

    def destroy(self):
        self.destroyed = True


class FakeWebview:
    def __init__(self):
        self.created = []
        self.screens = [type("Screen", (), {"width": 1920, "height": 1080})()]

    def create_window(self, title, url, **kw):
        w = FakeWindow(title=title, url=url, **kw)
        self.created.append(w)
        return w


class Bridge(unittest.TestCase):
    def test_companion_window_replaces_the_big_one_and_back(self):
        wv = FakeWebview()
        bridge = desktop.Bridge(wv, "http://127.0.0.1:1/mini/#k=x")
        main = FakeWindow()
        bridge._attach(main)
        self.assertTrue(bridge.mini(True))
        self.assertTrue(bridge.mini(True))  # asking twice does not open two
        self.assertEqual(len(wv.created), 1)
        mini = wv.created[0]
        self.assertFalse(main.visible)
        self.assertTrue(mini.kw["on_top"] and mini.kw["frameless"] and mini.kw["easy_drag"])
        self.assertEqual((mini.kw["width"], mini.kw["height"]), desktop.MINI_SIZE)
        self.assertLess(mini.kw["x"] + mini.kw["width"], 1920)  # inside the screen
        self.assertLess(mini.kw["y"] + mini.kw["height"], 1080)
        bridge.mini(False)
        self.assertTrue(main.visible and mini.destroyed)

    def test_closing_the_companion_any_other_way_brings_the_big_window_back(self):
        wv = FakeWebview()
        bridge = desktop.Bridge(wv, "http://127.0.0.1:1/mini/#k=x")
        main = FakeWindow()
        bridge._attach(main)
        bridge.mini(True)
        self.assertFalse(main.visible)
        wv.created[0].events.closed.fire()  # Alt+F4 on the small window
        self.assertTrue(main.visible)
        bridge.mini(True)  # and it can be opened again
        self.assertEqual(len(wv.created), 2)

    def test_the_companion_opens_fully_visible_at_any_display_scaling(self):
        real = desktop._scale
        try:
            for scale in (1.0, 1.25, 1.5):
                desktop._scale = lambda s=scale: s
                wv = FakeWebview()  # the screen is reported in real pixels: 1920 x 1080
                x, y = desktop.mini_place(wv)
                w, h = desktop.MINI_SIZE
                visible_w, visible_h = 1920 / scale, 1080 / scale  # what positions mean after pywebview's scaling
                self.assertGreaterEqual(x, desktop.MINI_MARGIN)
                self.assertLessEqual(x + w, visible_w - desktop.MINI_MARGIN, scale)
                self.assertLessEqual(y + h, visible_h - desktop.MINI_MARGIN, scale)
                self.assertLess(y, visible_h / 3)  # upper part of the screen, easy to see
        finally:
            desktop._scale = real

    def test_the_companion_remembers_where_you_put_it(self):
        real = desktop._scale
        desktop._scale = lambda: 1.25
        (desktop.config.HOME / "companion.json").unlink(missing_ok=True)
        try:
            wv = FakeWebview()
            bridge = desktop.Bridge(wv, "http://127.0.0.1:1/mini/#k=x")
            bridge._attach(FakeWindow())
            bridge.mini(True)
            wv.created[0].events.moved.fire_with(250, 375)  # dragged there (real pixels)
            bridge.mini(False)
            bridge.mini(True)
            self.assertEqual((wv.created[1].kw["x"], wv.created[1].kw["y"]), (200, 300))  # same spot again
            self.assertEqual(desktop.mini_place(wv, (5000, -900)), desktop.mini_place(wv))  # gone off-screen: default
            x, y = desktop.mini_place(wv, (1500, 800))  # partly outside: pulled fully onto the screen
            self.assertLessEqual(x + desktop.MINI_SIZE[0], 1920 / 1.25 - desktop.MINI_MARGIN)
            self.assertLessEqual(y + desktop.MINI_SIZE[1], 1080 / 1.25 - desktop.MINI_MARGIN)
        finally:
            desktop._scale = real
            (desktop.config.HOME / "companion.json").unlink(missing_ok=True)

    def test_the_dotted_v_icon_is_packaged_and_given_to_the_companion(self):
        import struct
        from pathlib import Path

        raw = desktop.ICON.read_bytes()  # lives in data/, which the build and the wheel both ship
        reserved, kind, count = struct.unpack_from("<HHH", raw)
        self.assertEqual((reserved, kind), (0, 1))  # a real .ico
        widths = {raw[6 + 16 * i] or 256 for i in range(count)}
        self.assertTrue({16, 32, 48, 256} <= widths)  # taskbar, title bar, Alt+Tab, Explorer
        web = Path(__file__).resolve().parent.parent / "ui" / "web" / "app"
        self.assertTrue((web / "favicon.ico").is_file() and (web / "icon.png").is_file())
        wv = FakeWebview()
        bridge = desktop.Bridge(wv, "http://127.0.0.1:1/mini/#k=x")
        bridge._attach(FakeWindow())
        bridge.mini(True)
        if sys.platform == "win32":
            self.assertEqual(len(wv.created[0].events.shown.handlers), 1)
            wv.created[0].events.shown.fire()  # no real window behind it: must not raise


class Pages(unittest.TestCase):
    def test_companion_page_is_served_although_a_folder_has_the_same_name(self):
        import threading
        import urllib.request
        from http.server import ThreadingHTTPServer
        from pathlib import Path

        from vaelon import server

        ui = Path(tempfile.mkdtemp())
        (ui / "index.html").write_text("<html>full window</html>", "utf-8")
        (ui / "mini.html").write_text("<html>companion</html>", "utf-8")  # what the static export produces
        (ui / "mini").mkdir()
        (ui / "mini" / "__next.mini.txt").write_text("data", "utf-8")
        old = os.environ.get("VAELON_UI_DIR")
        os.environ["VAELON_UI_DIR"] = str(ui)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(server.Service(Config(provider="mock")), "t", 0))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{srv.server_address[1]}"
            for path in ("/mini", "/mini/", "/mini/?r=1"):
                self.assertIn("companion", urllib.request.urlopen(base + path, timeout=5).read().decode(), path)
            self.assertIn("full window", urllib.request.urlopen(base + "/", timeout=5).read().decode())
        finally:
            srv.shutdown()
            srv.server_close()
            if old is None:
                os.environ.pop("VAELON_UI_DIR", None)
            else:
                os.environ["VAELON_UI_DIR"] = old


if __name__ == "__main__":
    unittest.main()
