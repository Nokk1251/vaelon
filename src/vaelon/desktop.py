"""Vaelon as a desktop app: one process runs the core (API + scheduler) and a native window
(Edge WebView2 on Windows, WebKit on macOS, GTK/Qt on Linux) - no browser, no terminal juggling.

Install: pip install "vaelon[app]"  then  vaelon app      (or the packaged Vaelon.exe)
"""
from __future__ import annotations

import sys
import threading
import webbrowser
from pathlib import Path

import requests

from . import config, scheduler, server
from .security.confirm import deny_all


class PortTaken(RuntimeError):
    """Something that is NOT Vaelon answers on Vaelon's port: the app must not open (it would hand over its key)."""


def _core_running(port: int) -> bool:
    """True when the REAL Vaelon core already runs on the port (it proved it knows the access key - the key itself is
    never sent). Raises PortTaken when something else answers there."""
    from .security import proof

    try:
        requests.get(f"http://127.0.0.1:{port}/health", timeout=3)  # 1 s was too short on a busy PC (flaky check)
    except requests.RequestException:
        return False
    n = proof.nonce()
    try:
        got = requests.get(f"http://127.0.0.1:{port}/hello", params={"n": n}, timeout=3).json().get("proof")
    except (requests.RequestException, ValueError, AttributeError):
        got = None
    if proof.check(server.get_token(), "vaelon-core", n, got):
        return True
    raise PortTaken(f"Another program is using Vaelon's port {port}. Close it (or set a different api_port in "
                    f"~/.vaelon/config.json) and start Vaelon again.")


def start_core(cfg):
    """Start API + scheduler in background threads unless a core already runs. Returns the server or None."""
    if _core_running(cfg.api_port):
        return None
    try:  # the app opens on a fresh conversation; the earlier ones stay in the list (❏)
        from . import conversation

        conversation.new()
    except Exception:
        pass
    srv = server.serve(cfg)
    threading.Thread(target=srv.serve_forever, daemon=True, name="vaelon-api").start()

    def jobs():
        from .agent import Agent
        import time

        while True:
            try:
                scheduler.run_due(lambda: Agent(cfg, approver=deny_all))
            except Exception:
                pass
            time.sleep(30)

    threading.Thread(target=jobs, daemon=True, name="vaelon-scheduler").start()
    return srv


MINI_SIZE = (380, 148)
MINI_MARGIN = 24  # px kept free between the companion and the screen edges


def _scale() -> float:
    """Windows display scaling (1.25 at 125 %). pywebview multiplies a window's x/y by it, but reports screen sizes in
    real pixels - mixing the two put the companion almost completely off the screen."""
    try:
        import ctypes

        if sys.platform != "win32":
            return 1.0  # macOS: window positions are already in points
        return (ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100) or 1.0
    except Exception:
        return 1.0


def _areas(wv) -> list[tuple[float, float, float, float]]:
    """The usable part of every screen (without the taskbar), in the units window positions are given in."""
    s, out = _scale(), []
    for scr in getattr(wv, "screens", None) or []:
        frame = getattr(scr, "frame", None)  # WorkingArea on Windows
        try:
            x, y, w, h = frame.X, frame.Y, frame.Width, frame.Height
        except AttributeError:
            x, y, w, h = getattr(scr, "x", 0), getattr(scr, "y", 0), scr.width, scr.height
        out.append((x / s, y / s, w / s, h / s))
    return out


def mini_place(wv, saved: tuple | None = None) -> tuple[int, int] | None:
    """Where the companion opens: where you left it last time if that is still on a screen, else top right of the
    main screen - always fully visible."""
    areas = _areas(wv)
    if not areas:
        return None
    w, h, m = MINI_SIZE[0], MINI_SIZE[1], MINI_MARGIN
    area = areas[0]
    if saved:
        sx, sy = saved
        for a in areas:  # the screen the saved spot lies on (a second monitor may be gone by now)
            if a[0] - w / 2 <= sx <= a[0] + a[2] - w / 2 and a[1] - h / 2 <= sy <= a[1] + a[3] - h / 2:
                area = a
                break
        else:
            saved = None
    ax, ay, aw, ah = area
    x, y = saved if saved else (ax + aw - w - m * 2, ay + ah * 0.12)
    x = min(max(x, ax + m), ax + aw - w - m)
    y = min(max(y, ay + m), ay + ah - h - m)
    return int(x), int(y)


def _saved_place() -> tuple | None:
    import json

    try:
        d = json.loads((config.HOME / "companion.json").read_text("utf-8"))
        return float(d["x"]), float(d["y"])
    except Exception:
        return None


def _save_place(x: float, y: float) -> None:
    import json

    try:
        (config.HOME / "companion.json").write_text(json.dumps({"x": round(x), "y": round(y)}), "utf-8")
    except OSError:
        pass
ICON = Path(__file__).resolve().parent / "data" / "vaelon.ico"
APP_ID = "Nokk7.Vaelon"


def _own_taskbar_entry() -> None:
    """Windows groups taskbar buttons by app id: without one, `vaelon app` shows up under Python's icon."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def _brand(window) -> None:
    """Give a window the dotted-V icon. The packaged Vaelon.exe already carries it (the window takes the exe's
    icon); this covers `vaelon app` started from Python. Windows only - elsewhere `webview.start(icon=...)` does it."""
    if sys.platform != "win32" or not ICON.is_file():
        return

    def apply():
        try:
            from System import Action  # pythonnet, loaded by pywebview on Windows
            from System.Drawing import Icon

            form = window.native
            icon = Icon(str(ICON))

            def set_icon():
                form.Icon = icon

            form.Invoke(Action(set_icon)) if form.InvokeRequired else set_icon()
        except Exception:
            pass  # an icon is never worth a crash

    window.events.shown += apply


class Bridge:
    """What the page may ask the desktop shell to do (exposed to the page as `pywebview.api`). Window handling
    only: switch between the full window and the small always-on-top companion. It cannot run or open anything."""

    def __init__(self, webview, mini_url: str):
        self._webview, self._mini_url = webview, mini_url
        self._main = None
        self._mini = None
        self._at = None  # where you dragged the companion (logical units), saved when it closes

    def _attach(self, main) -> None:  # "_": pywebview never exposes it to the page
        self._main = main

    def is_desktop(self) -> bool:
        return True

    def mini(self, on: bool = True) -> bool:
        """True: hide the big window and show the small floating one. False: the other way round."""
        wv = self._webview
        if on:
            if self._mini is None:
                x = y = None
                try:
                    x, y = mini_place(wv, _saved_place()) or (None, None)
                except Exception:
                    pass
                self._mini = wv.create_window("Vaelon", self._mini_url, js_api=self, width=MINI_SIZE[0],
                                              height=MINI_SIZE[1], x=x, y=y, frameless=True, easy_drag=True,
                                              on_top=True, resizable=False, shadow=True, background_color="#050304",
                                              min_size=MINI_SIZE)
                self._mini.events.closed += self._mini_closed  # closed any other way: bring the big window back
                try:
                    self._mini.events.moved += self._moved
                except AttributeError:
                    pass
                _brand(self._mini)
            if self._main is not None:
                self._main.hide()
            return True
        mini, self._mini = self._mini, None
        self._remember()
        if self._main is not None:
            self._main.show()
        if mini is not None:
            try:
                mini.destroy()
            except Exception:
                pass
        return True

    def _moved(self, x, y) -> None:
        s = _scale()  # reported in real pixels: kept in the units it is opened with
        self._at = (x / s, y / s)

    def _remember(self) -> None:
        if self._at:
            _save_place(*self._at)

    def _mini_closed(self) -> None:
        self._remember()
        if self._mini is not None:
            self._mini = None
            if self._main is not None:
                try:
                    self._main.show()
                except Exception:
                    pass


def _alert(text: str) -> None:
    """A plain message box (the app's own window cannot open safely in this case)."""
    if sys.platform == "darwin":
        from . import platform_mac

        return platform_mac.alert(text)
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, "Vaelon", 0x10)
    except Exception:
        print(text)


def run(cfg=None) -> None:
    cfg = cfg or config.Config.load()
    if server.ui_dir() is None:
        raise SystemExit("The interface is not built. Run:  cd ui/web && npm install && npm run build")
    try:
        srv = start_core(cfg)
    except PortTaken as e:
        _alert(str(e))
        raise SystemExit(str(e)) from None
    # the access key travels in the URL fragment: never sent over the network, read once and removed by the UI
    base = f"http://127.0.0.1:{cfg.api_port}"
    url = f"{base}/#k={server.get_token()}"
    try:
        import webview
    except ImportError:
        print('Native window needs: pip install "vaelon[app]" - opening your browser instead.')
        webbrowser.open(url)
        if srv:
            threading.Event().wait()
        return
    _own_taskbar_entry()
    bridge = Bridge(webview, f"{base}/mini/#k={server.get_token()}")
    main = webview.create_window("VAELON", url, js_api=bridge, width=1280, height=820, min_size=(720, 520),
                                 background_color="#050304")
    bridge._attach(main)
    _brand(main)
    webview.start(private_mode=False, storage_path=str(config.HOME / "webview"),
                  icon=str(ICON) if ICON.is_file() else None)
    if srv:
        srv.shutdown()
