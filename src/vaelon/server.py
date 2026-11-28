"""Local HTTP API + the built web UI (desktop app / browser), same origin.

Security: binds 127.0.0.1 only, requires a random bearer token (~/.vaelon/api_token), validates the Host
header (DNS-rebinding defence), allows CORS only from localhost origins. Dangerous actions appear as a
pending approval that only an authenticated client can accept.

  POST /chat      {"text": "...", "spoken"?: bool, "screen"?: bool} -> {"job": id}   several jobs may run at once
                  (screen = the user switched screen sharing on: see_screen may run without an extra click)
  GET  /job/<id>                               -> {"status": running|approval|done, "approval":{...}, "answer": "...",
                                                   "steps": [...], "partial": "..."}
  GET  /jobs                                   -> the unfinished jobs
  POST /approve   {"job": id, "allow": bool}
  POST /cancel    {"job": id}                  -> stop a running job
  POST /open      {"path": "...", "reveal"?: bool} -> open a file Vaelon created (output folder only, documents only)
  GET  /file?path=...                          -> the bytes of such a file (in-app audio player / picture preview)
  POST /upload    raw bytes + X-Filename       -> attach a picture or document ({"path", "name", "image"})
  GET  /notices?since=<id>                     -> reminders that fired, results of scheduled tasks
  GET  /catalog                                -> every tool, skill, command, example + what Vaelon knows
  GET  /voice  |  POST /voice {"voice": {...}}  -> Voice Designer profile
  POST /tts    {"text": "...", "voice"?: {...}} -> audio/wav
  POST /history/clear                          -> start a new conversation
  GET  /calendar?from&days | POST /calendar    -> the calendar panel (calendar_api.py)
  GET  /bills | POST /bills {"action": ...}    -> the bills & invoices panel (bills_api.py); Vaelon never pays
  GET  /budget?month=YYYY-MM | POST /budget    -> the budget tab (budget_api.py)
  GET  /deals | POST /deals {"action": ...}    -> the deals tab (deals_api.py)
  POST /feedback {"kind", "text", "mail"?}    -> the Help page: a text note in <output>/Feedback (nothing is sent)
  GET  /health
"""
from __future__ import annotations

import hmac
import json
import mimetypes
import os
import secrets
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import config
from .agent import Agent
from .security.confirm import ConfirmRequest

APPROVAL_TIMEOUT = 120
INTEGRITY = {"ok": True}
STATIC_TYPES = {".html": "text/html; charset=utf-8", ".js": "application/javascript", ".css": "text/css",
                ".json": "application/json", ".svg": "image/svg+xml", ".woff2": "font/woff2", ".txt": "text/plain"}
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
       "connect-src 'self' ws://127.0.0.1:* ws://localhost:*; img-src 'self' data: blob:; media-src 'self' blob:; "
       "font-src 'self'; "
       "frame-ancestors 'none'; base-uri 'self'; object-src 'none'; form-action 'self'")


def ui_dir() -> Path | None:
    """Built web UI. The installed app: only its packaged copy (vaelon/webui). From source: $VAELON_UI_DIR, then the
    fresh build of the checkout (ui/web/out), then a packaged copy."""
    import sys

    here = Path(__file__).resolve().parent
    packaged, source = here / "webui", here.parent.parent / "ui" / "web" / "out"
    # the installed app serves ONLY its own interface: an environment variable must never point the signed app at
    # another folder (that page would get the access key) - VAELON_UI_DIR is for developers running from source.
    # From source the checkout's own build goes first: scripts/build_app.py leaves a copy in vaelon/webui, and that
    # copy would otherwise hide every later `npm run build` (the app showed an interface days old).
    if getattr(sys, "frozen", False):
        order: tuple = (packaged,)
    else:
        order = (os.environ.get("VAELON_UI_DIR"), source, packaged)
    for cand in order:
        if cand and (Path(cand) / "index.html").exists():
            return Path(cand).resolve()
    return None
LOCAL_ORIGINS = ("http://localhost:", "http://127.0.0.1:")


def get_token() -> str:
    """Access key for the local API. Sealed in the vault (DPAPI on Windows); `vaelon token` prints it.
    A plaintext copy is kept in ~/.vaelon/api_token only for the developer UI (`npm run dev`)."""
    from .security import vault

    sealed = vault.read_secret("api_token")
    if sealed:
        return sealed.decode()
    legacy = config.HOME / "api_token"
    tok = legacy.read_text("utf-8").strip() if legacy.exists() else secrets.token_urlsafe(32)
    vault.write_secret("api_token", tok.encode())
    legacy.unlink(missing_ok=True)  # do not leave the key lying around in plain text
    return tok


MAX_PARALLEL = 4  # tasks that work at the same time (each is its own agent); more wait in a queue
MAX_OPEN = 12  # unfinished jobs accepted before /chat answers "busy"


class Cancelled(BaseException):
    """Raised inside a job's event callback when the user cancels it. A BaseException on purpose: nothing in the
    agent loop swallows it, and leaving the model stream closes the connection (no more tokens are paid for)."""


class Job:
    def __init__(self, text: str = "", user: str = ""):
        self.user = user  # company mode: who started it (a person who is not the owner sees only their own)
        self.status, self.answer, self.approval = "running", "", None
        self.partial, self.tool = "", ""
        self.text = text
        self.steps: list[dict] = []  # what this task did, for the app's task inspector
        self.files: list[dict] = []  # files this task created (the app shows an Open button for each)
        self.queued, self.cancelled = True, False
        self.learned: list[str] = []  # facts Vaelon picked up about the user during this job
        self.event, self.allowed = threading.Event(), False
        self.rev, self.cond = 0, threading.Condition()
        self.created = time.time()
        self.finished = 0.0
        self.first = 0.0  # when the first words of the answer appeared (for the /speed read-out)

    def step(self, label: str, detail: str = "") -> None:
        self.steps.append({"t": round(time.time() - self.created, 1), "label": label, "detail": detail})
        del self.steps[:-40]

    def bump(self) -> None:
        """Something changed: wake every long-polling client at once (no busy polling)."""
        with self.cond:
            self.rev += 1
            self.cond.notify_all()

    def wait_change(self, since: int, timeout: float = 15.0) -> None:
        with self.cond:
            if self.rev == since:
                self.cond.wait(timeout)

    def snapshot(self) -> dict:
        return {"status": self.status, "approval": self.approval, "answer": self.answer,
                "partial": self.partial, "tool": self.tool, "rev": self.rev, "learned": self.learned,
                "text": self.text[:300], "steps": self.steps, "queued": self.queued, "cancelled": self.cancelled,
                "files": self.files,
                "first_after": round(self.first - self.created, 2) if self.first else None,
                "elapsed": round((self.finished or time.time()) - self.created, 1)}


class Service:
    def __init__(self, cfg, agent_factory=None):
        self.cfg, self.jobs, self.lock = cfg, {}, threading.Lock()
        self.agent_factory = agent_factory or Agent
        self._agent = None
        self.agent_lock = threading.Lock()  # agents that cannot fork answer one at a time
        self.make_lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(MAX_PARALLEL)
        self.work_history: dict[str, list] = {}  # company mode: each person's own conversation, kept in memory only

    def agent(self, approver=None):
        """The single long-lived agent (created on first use). Every task runs on a fork of it."""
        with self.make_lock:
            if self._agent is None:
                from .security.confirm import deny_all

                self._agent = self.agent_factory(self.cfg, approver=approver or deny_all)
            return self._agent

    def open_jobs(self) -> int:
        return sum(1 for j in list(self.jobs.values()) if j.status != "done")

    def start(self, text: str, spoken: bool = False, screen: bool = False) -> str:
        from . import company

        who = company.user() if company.enabled() else None  # read ONCE: a lock right now must not make it the owner
        if company.enabled() and not who:
            raise company.Denied("Vaelon is locked - sign in first")  # also for the Live bridge and anything else
        guest = bool(who) and who["role"] != "owner"  # someone else at the keyboard: work mode, never the owner's memory
        bound = (who["id"] if who else None, company.workspace())
        jid, job = uuid.uuid4().hex[:12], Job(text, who["id"] if who else "")
        self.jobs[jid] = job

        def approver(req: ConfirmRequest) -> bool:
            if job.cancelled:
                return False
            # a fresh id per question: "Allow" answers THIS card only (a double click or a stale card cannot approve
            # the next action of the same task)
            job.approval = {"tool": req.tool, "summary": req.summary, "tainted": req.tainted, "id": uuid.uuid4().hex[:10],
                            "note": req.note}
            job.status, job.allowed = "approval", False
            job.event.clear()
            if job.cancelled:  # stopped while the card was being prepared: no 2-minute wait
                job.approval, job.status = None, "running"
                return False
            job.step("waiting for your approval", req.tool)
            job.bump()
            job.event.wait(APPROVAL_TIMEOUT)
            ok, job.approval, job.status = job.allowed and not job.cancelled, None, "running"
            job.bump()
            return ok

        def on_event(kind, data):
            if job.cancelled:
                raise Cancelled()
            if kind == "token":
                if not job.partial:
                    job.step("writing the answer")
                    job.first = job.first or time.time()
                job.partial += data
            elif kind == "reset":
                job.partial = ""
            elif kind == "tool":
                job.tool = data
                job.step(str(data))
            elif kind == "detail" and job.steps:
                job.steps[-1]["detail"] = str(data)[:120]
            elif kind == "learn":
                job.learned.append(str(data))
            elif kind == "file":
                p = Path(str(data))
                if p.is_file() and not any(f["path"] == str(p) for f in job.files):
                    job.files.append({"path": str(p), "name": p.name, "kb": max(1, p.stat().st_size // 1024)})
            job.bump()

        def work():
            from . import company as _co

            _co.bind(*bound)  # this task keeps its person and company even if someone signs in or switches meanwhile
            with self.slots:  # at most MAX_PARALLEL tasks think at once; the rest wait their turn
                job.queued = False
                job.step("started")
                job.bump()
                try:
                    if job.cancelled:
                        raise Cancelled()
                    main = self.agent(approver)
                    kw = {"spoken": True} if spoken else {}
                    if screen and not guest:
                        kw["screen"] = True
                    if hasattr(main, "fork") and guest:
                        twin = main.fork(approver)
                        twin.work_mode(self.work_history.setdefault(who["id"], []))
                        job.answer = twin.run(text, on_event=on_event, **kw)
                    elif hasattr(main, "fork"):
                        job.answer = main.fork(approver).run(text, on_event=on_event, **kw)
                    else:  # a custom agent without fork(): keep the old one-at-a-time behaviour
                        with self.agent_lock:
                            main.approver = approver
                            job.answer = main.run(text, on_event=on_event, **kw)
                except Cancelled:
                    job.answer, job.partial = "", ""
                except Exception as e:
                    job.answer = f"error: {e}"
                job.step("cancelled" if job.cancelled else "done")
                job.status, job.finished = "done", time.time()
                job.bump()
                self._gc()

        threading.Thread(target=work, daemon=True).start()
        return jid

    def cancel(self, jid: str) -> bool:
        """Stop a task: it ends at its next step (and a pending approval is refused)."""
        job = self.jobs.get(jid)
        if not job or job.status == "done":
            return False
        job.cancelled, job.allowed = True, False
        job.event.set()
        job.bump()
        return True

    def _gc(self, keep_seconds: float = 900) -> None:
        """Forget finished jobs after 15 minutes so memory does not grow forever."""
        now = time.time()
        for jid in [j for j, job in list(self.jobs.items()) if job.status == "done" and now - job.created > keep_seconds]:
            self.jobs.pop(jid, None)

    def approve(self, jid: str, allow: bool, card: str = "") -> bool:
        job = self.jobs.get(jid)
        if not job or job.status != "approval" or not job.approval:
            return False
        if allow and not hmac.compare_digest(str(card).encode(), str(job.approval.get("id", "")).encode()):
            return False  # "Allow" must name the card the user is looking at; "Deny" is always safe
        job.allowed = bool(allow)
        job.event.set()
        return True


MAX_UPLOAD = 15_000_000
UPLOAD_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md",
                ".csv", ".json", ".log", ".py", ".js", ".ts", ".html", ".xml", ".yaml", ".yml"}


def save_upload(cfg, name: str, data: bytes) -> dict:
    """Keep an attached file in <output folder>/Attachments so the tools can read it. Documents and pictures only."""
    from .security.policy import resolve_path
    from .tools.create import _safe_name, out_dir

    ext = Path(name).suffix.lower()
    if ext not in UPLOAD_TYPES:
        raise ValueError(f"files of type '{ext or '?'}' cannot be attached (pictures and documents only)")
    folder = out_dir(cfg) / "Attachments"
    stem = _safe_name(Path(name).stem, "file")
    path = folder / f"{stem}{ext}"
    k = 2
    while path.exists():
        path = folder / f"{stem} ({k}){ext}"
        k += 1
    path = resolve_path(str(path), cfg.allowed_roots)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    from . import guardian

    guardian.mark_from_internet(path)  # Office / Windows / macOS treat an attached file as downloaded
    return {"path": str(path), "name": path.name, "kb": max(1, len(data) // 1024),
            "image": ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")}


def open_created(cfg, path: str, reveal: bool = False, launch=None) -> tuple[bool, str]:
    """Open a file Vaelon created (or show it in its folder). Only files inside the output folder, and only
    document/audio/image types - never programs or scripts, whatever a page or a model asks for."""
    from .tools.create import OPENABLE, out_dir

    from .security.policy import odd_path

    if not isinstance(path, str) or odd_path(path):
        return False, "bad path"
    try:
        p = Path(path).resolve()
        folder = out_dir(cfg).resolve()
    except OSError:
        return False, "bad path"
    if folder not in p.parents or not p.is_file():
        return False, "only files in Vaelon's output folder can be opened"
    if p.suffix.lower() not in OPENABLE:
        return False, "this file type is not opened from the app"
    try:
        if launch:
            launch(p, reveal)
        elif sys.platform == "darwin":
            from . import platform_mac

            platform_mac.open_file(str(p), reveal)  # `open` / `open -R`, an argument list
        elif reveal:
            import subprocess

            subprocess.Popen(["explorer", "/select,", str(p)])
        else:
            os.startfile(str(p))  # noqa: S606 - a document type, inside our own folder
    except (OSError, AttributeError) as e:
        return False, str(e)[:120]
    return True, ""


class _Server(ThreadingHTTPServer):
    """The API server. No SO_REUSEADDR and, on Windows, SO_EXCLUSIVEADDRUSE: no other program can bind Vaelon's port
    while it runs and receive the app's requests (and with them the access key and anything typed)."""
    allow_reuse_address = False
    daemon_threads = True
    MAX_CONNECTIONS = 64

    def __init__(self, *a, **kw):
        self._slots = threading.BoundedSemaphore(self.MAX_CONNECTIONS)
        super().__init__(*a, **kw)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):  # a flood of idle connections cannot exhaust the app
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def server_bind(self):
        from .security.proof import exclusive

        exclusive(self.socket)
        super().server_bind()


def make_handler(service: Service, token: str, port: int):
    class H(BaseHTTPRequestHandler):
        timeout = 20  # a connection that sends nothing (or drips) is closed - it cannot hold a thread for ever

        def log_message(self, *a):
            pass

        def _send(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            origin = self.headers.get("Origin", "")
            if origin.startswith(LOCAL_ORIGINS):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Filename")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _stream_pcm(self, voiced) -> None:
            """Raw 16-bit mono PCM, written as it is made. HTTP/1.0: the end of the audio closes the connection."""
            self.send_response(200)
            self.send_header("Content-Type", f"audio/L16; rate={voiced.rate}; channels=1")
            self.send_header("X-Sample-Rate", str(voiced.rate))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            origin = self.headers.get("Origin", "")
            if origin.startswith(LOCAL_ORIGINS):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Expose-Headers", "X-Sample-Rate")
            self.end_headers()
            self.close_connection = True
            try:  # small pieces must leave at once: Windows otherwise holds each one up to 200 ms (heard as gaps)
                import socket

                self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
            try:
                for part in voiced.chunks:
                    self.wfile.write(part)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # the app stopped listening (you interrupted): stop reading the cloud too
            finally:
                voiced.chunks.close()

        def _gate(self, route: str, post: bool = False) -> bool:
            """Company mode. True = already answered (refused)."""
            from . import company

            if not company.enabled() or route == "/company":
                return False
            u = company.user()
            if not u:
                if post:
                    self._drain()
                self._send(423, {"error": "Vaelon is locked - sign in", "locked": True})
                return True
            allowed = (route.startswith("/job/") or route in ("/bills", "/budget", "/deals", "/quotes", "/recurring",
                       "/payment-reminders", "/company", "/journal", "/jobs",
                       "/chat", "/stt", "/tts", "/upload", "/approve", "/cancel", "/file", "/open", "/catalog")
                       or (route == "/voice" and not post))  # only what is listed; everything else is the owner's
            if u["role"] != "owner" and (not allowed or (company.workspace() == company.PERSONAL and route != "/company")):
                if post:
                    self._drain()
                self._send(403, {"error": "this is the owner's personal part of Vaelon"})
                return True
            return False

        def _mine(self, job) -> bool:
            """A person who is not the owner sees and steers only their own tasks."""
            from . import company

            if not company.enabled():
                return True
            u = company.user()
            return bool(u) and (u["role"] == "owner" or job.user == u["id"])

        def handle_one_request(self):
            from .company import Denied

            try:
                return super().handle_one_request()
            except Denied as e:  # a role check deep inside an API call
                try:
                    self._send(403, {"ok": False, "error": str(e)})
                except Exception:
                    pass

        def _foreign(self) -> bool:
            """A request from a web page that is not Vaelon's own (another site, a file, a sandboxed frame)."""
            origin = self.headers.get("Origin", "")
            return bool(origin) and not origin.startswith(LOCAL_ORIGINS)

        def _authed(self) -> bool:
            host = self.headers.get("Host", "").split(":")[0]
            if host not in ("127.0.0.1", "localhost"):
                return False
            origin = self.headers.get("Origin", "")
            if origin and not origin.startswith(LOCAL_ORIGINS):
                return False  # a web page from elsewhere: refused on every route, whatever it carries
            got = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            return hmac.compare_digest(got.encode("utf-8", "replace"), token.encode())

        def _static(self):
            """Serve the built web UI (desktop app / browser) from the same origin as the API."""
            root = ui_dir()
            host = self.headers.get("Host", "").split(":")[0]
            if root is None or host not in ("127.0.0.1", "localhost"):
                return self._send(404, {"error": "not found"})
            rel = unquote(self.path.split("?")[0].split("#")[0]).lstrip("/") or "index.html"
            f = (root / rel).resolve()
            if root not in f.parents and f != root:
                return self._send(404, {"error": "not found"})
            if f.is_dir():
                # the static export writes a page as "mini.html" NEXT TO a folder "mini" (its data files)
                f = f / "index.html" if (f / "index.html").is_file() else f.with_suffix(".html")
            if not f.exists() and not f.suffix:
                f = f.with_suffix(".html")
            if not f.is_file():
                return self._send(404, {"error": "not found"})
            body = f.read_bytes()
            if f.suffix == ".html":
                from . import tts

                tts.UI_UP.set()  # the window is up and loading its page: now the voices may load
            ctype = STATIC_TYPES.get(f.suffix.lower()) or mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("Cache-Control", "no-cache" if f.suffix == ".html" else "max-age=31536000, immutable")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self._send(204, {})

        def do_GET(self):
            if self.path == "/health":
                from . import tts
                return self._send(200, {"ok": True, "tts": tts.available(), "integrity": INTEGRITY["ok"]})
            route = self.path.split("?")[0]
            if route == "/hello":  # "are you the real Vaelon?" - answered with a proof, never with the key itself
                from .security import proof

                n = parse_qs(self.path.partition("?")[2]).get("n", [""])[0]
                if self.headers.get("Host", "").split(":")[0] not in ("127.0.0.1", "localhost") or self._foreign():
                    return self._send(404, {"error": "not found"})
                if not proof.valid_nonce(n):
                    return self._send(400, {"error": "bad nonce"})
                return self._send(200, {"proof": proof.proof(token, "vaelon-core", n)})
            if not (route.startswith(("/job/", "/chats/")) or route in ("/chats", "/calendar", "/bills", "/budget", "/deals", "/quotes", "/recurring", "/payment-reminders", "/company", "/journal") or route in ("/catalog", "/voice", "/jobs", "/notices", "/file", "/settings", "/models", "/ollama/pull", "/models/local", "/update", "/library")):
                return self._static()
            if not self._authed():
                return self._send(403 if self._foreign() else 401, {"error": "unauthorized"})
            if self._gate(route):
                return
            if route == "/company":  # who is signed in, which company is open, the people and companies
                from . import company

                return self._send(200, company.state())
            if route == "/journal":  # the journal of the open company (who changed what), and whether it is intact
                from . import company, journal

                if not company.can("journal.read"):
                    return self._send(403, {"error": "your role may not read the journal"})
                ok, what = journal.verify()
                return self._send(200, {"entries": journal.read(500), "intact": ok, "check": what})
            if route == "/notices":
                from . import reminders

                try:
                    since = int(parse_qs(self.path.partition("?")[2]).get("since", ["0"])[0])
                except ValueError:
                    since = 0
                return self._send(200, {"notices": reminders.notices_since(since)})
            if route == "/file":  # a file Vaelon created, for the in-app preview (audio player, pictures)
                wanted = parse_qs(self.path.partition("?")[2]).get("path", [""])[0]
                ok, why = open_created(service.cfg, wanted, launch=lambda p, r: None)
                if not ok:
                    return self._send(403, {"error": why})
                body = Path(wanted).resolve().read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mimetypes.guess_type(wanted)[0] or "application/octet-stream")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Cache-Control", "no-store")
                origin = self.headers.get("Origin", "")
                if origin.startswith(LOCAL_ORIGINS):
                    self.send_header("Access-Control-Allow-Origin", origin)
                self.end_headers()
                self.wfile.write(body)
                return
            if route == "/jobs":
                return self._send(200, {"jobs": [{"id": jid, **job.snapshot()} for jid, job in
                                                 list(service.jobs.items()) if job.status != "done" and self._mine(job)]})
            if route == "/deals":  # the sales pipeline, for the app's deals tab
                from . import deals_api

                return self._send(200, deals_api.overview())
            if route == "/quotes":  # quotes to clients, for the app's quotes tab (issue #43)
                from . import quotes_api

                return self._send(200, quotes_api.overview())
            if route == "/recurring":  # recurring invoices, for the app's Recurring tab (issue #44)
                from . import clientpay_api

                return self._send(200, clientpay_api.recurring_overview())
            if route == "/payment-reminders":  # reminder drafts for overdue invoices (issue #44)
                from . import clientpay_api

                return self._send(200, clientpay_api.reminders_overview(service.cfg))
            if route == "/budget":  # one month of the budget, for the app's budget tab
                from . import budget_api

                q = parse_qs(self.path.partition("?")[2])
                if q.get("view", [""])[0] == "cashflow":  # Money > Cash flow (issue #42)
                    from . import cashflow

                    try:
                        days = int(q.get("days", ["90"])[0])
                    except ValueError:
                        days = 90
                    return self._send(200, cashflow.forecast(days))
                return self._send(200, budget_api.overview(q.get("month", [""])[0]))
            if route == "/bills":  # bills, invoices and business details, for the app's bills panel
                from . import bills_api

                return self._send(200, bills_api.overview())
            if route == "/library":  # Settings > Your folders (owner only: not in the company allow-list)
                from . import library

                return self._send(200, {"folders": library.folders(), "allowed": list(service.cfg.allowed_roots)})
            if route == "/calendar":  # the next days of the calendar, for the app's calendar panel
                from . import calendar_api

                q = parse_qs(self.path.partition("?")[2])
                return self._send(200, calendar_api.days(q.get("from", [""])[0], q.get("days", ["14"])[0]))
            if route == "/chats":  # the list of conversations (titles are decrypted only here, for the owner's app)
                from . import conversation

                return self._send(200, {"chats": conversation.chats()})
            if route.startswith("/chats/"):
                from . import conversation

                found = conversation.messages(route[len("/chats/"):])
                return self._send(200 if found is not None else 404,
                                  {"messages": found} if found is not None else {"error": "no such chat"})
            if route == "/settings":  # for the Settings screen and the first-run setup: state, never secrets
                from . import settings

                return self._send(200, settings.snapshot(service.cfg, probe="probe=1" in self.path))
            if route == "/ollama/pull":  # how far the download of the local model is (?model= a model from the list)
                from . import modelpull

                choice = parse_qs(self.path.partition("?")[2]).get("model", [""])[0] or None
                return self._send(200, modelpull.status(service.cfg, choice))
            if route == "/models/local":  # the curated local models, this computer, and what fits it (never leaves it)
                from . import localmodels, settings

                seen = settings.ollama(service.cfg)
                in_use = service.cfg.model if service.cfg.provider == "ollama" else ""
                m = localmodels.machine()
                have = {n.removesuffix(":latest") for n in seen["models"]}
                host = (urlparse(service.cfg.base_url or "").hostname or "localhost").lower()
                return self._send(200, {"machine": m, "ollama": seen, "overhead_gb": localmodels.OVERHEAD_GB,
                                        "in_use": in_use,
                                        # the model in use (any name, also one outside the list) is downloaded
                                        "in_use_installed": bool(in_use) and in_use.removesuffix(":latest") in have,
                                        # Ollama on another computer: the advice below is for THIS one
                                        "remote": host not in ("localhost", "127.0.0.1", "::1"),
                                        "models": localmodels.assess(m, seen["models"], in_use)})
            if route == "/update":  # is there a newer Vaelon? only when the user turned it on or pressed "Check now"
                from . import updates

                now = parse_qs(self.path.partition("?")[2]).get("now", [""])[0] == "1"
                if not (now or service.cfg.update_check):
                    return self._send(200, {"enabled": False, "off": True})
                c = updates.check(force=now)
                return self._send(200, {k: c.get(k) for k in ("enabled", "current", "latest", "newer", "url", "error",
                                                              "checking")})
            if route == "/models":
                from . import settings

                names, problem = settings.models(service.cfg)
                return self._send(200, {"models": names, "error": problem})
            if route == "/catalog":
                from . import catalog

                from . import company

                agent = service.agent()
                lang = "bg" if "lang=bg" in self.path else "en"
                owner = not company.enabled() or (company.user() or {}).get("role") == "owner"
                return self._send(200, catalog.build(getattr(agent, "memory", None) if owner else None, lang, personal=owner))
            if route == "/voice":
                from . import tts

                cfg = config.Config.load()
                from . import stt

                from . import live

                return self._send(200, {"voice": tts.current_voice(cfg), "presets": tts.PRESETS,
                                        "limits": tts.LIMITS, "engine": cfg.tts_engine,
                                        "engines": tts.engines_status(), "stt": stt.engine(cfg),
                                        "live": live.status(cfg)})
            if self.path.startswith("/job/"):
                path, _, query = self.path[5:].partition("?")
                job = service.jobs.get(path)
                if not job or not self._mine(job):
                    return self._send(404, {"error": "no such job"})
                q = parse_qs(query)
                if "since" in q and job.status != "done":  # long-poll: answer as soon as something changes
                    try:
                        job.wait_change(int(q["since"][0]))
                    except ValueError:
                        pass
                return self._send(200, job.snapshot())
            self._send(404, {"error": "not found"})

        def _drain(self) -> None:
            """Read (and drop) a refused request's body, so the refusal arrives as an answer, not a cut connection."""
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if 0 < n <= 1_000_000:
                    self.rfile.read(n)
                elif n > 1_000_000:
                    self.close_connection = True
            except (ValueError, OSError):
                self.close_connection = True

        def do_POST(self):
            if not self._authed():
                self._drain()
                return self._send(403 if self._foreign() else 401, {"error": "unauthorized"})
            if self._gate(self.path, post=True):
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._send(400, {"error": "bad length"})
            if n < 0:
                return self._send(400, {"error": "bad length"})
            if self.path == "/stt":  # microphone audio (raw bytes, not JSON)
                from . import stt

                if n <= 0 or n > stt.MAX_BYTES:
                    return self._send(413, {"error": "recording missing or too long"})
                audio = self.rfile.read(n)
                try:
                    text = stt.transcribe(audio, self.headers.get("Content-Type", "audio/webm"))
                except Exception as e:
                    return self._send(503, {"error": str(e)[:200]})
                return self._send(200, {"text": text})
            if self.path == "/upload":  # a file you attach in the app (raw bytes, the name in X-Filename)
                if n <= 0 or n > MAX_UPLOAD:
                    return self._send(413, {"error": "file missing or larger than 15 MB"})
                try:
                    saved = save_upload(service.cfg, unquote(self.headers.get("X-Filename", "file")), self.rfile.read(n))
                except Exception as e:
                    return self._send(400, {"error": str(e)[:200]})
                return self._send(200, saved)
            if n > 100_000:
                return self._send(413, {"error": "too large"})
            try:
                data = json.loads(self.rfile.read(n) or b"{}")
            except (ValueError, UnicodeDecodeError, RecursionError):
                return self._send(400, {"error": "bad json"})
            if not isinstance(data, dict):
                return self._send(400, {"error": "the body must be a JSON object"})
            if self.path == "/chat" and isinstance(data.get("text"), str) and data["text"].strip():
                if service.open_jobs() >= MAX_OPEN:
                    return self._send(429, {"error": "too many tasks are running - wait for one to finish"})
                return self._send(200, {"job": service.start(data["text"], spoken=bool(data.get("spoken")),
                                                             screen=bool(data.get("screen")))})
            if self.path == "/cancel":
                job = service.jobs.get(str(data.get("job")))
                return self._send(200, {"ok": bool(job) and self._mine(job) and service.cancel(str(data.get("job")))})
            if self.path == "/company":
                from . import company_api

                origin = self.headers.get("Origin", "")
                if origin and not origin.startswith(LOCAL_ORIGINS):
                    return self._send(403, {"error": "only the app itself may change company mode"})
                code, body = company_api.act(service, data)
                return self._send(code, body)
            if self.path == "/feedback":  # the Help page: saved as a text file; mail only through the user's own program
                from . import feedback

                origin = self.headers.get("Origin", "")
                if origin and not origin.startswith(LOCAL_ORIGINS):
                    return self._send(403, {"error": "only the app itself may save feedback"})
                try:
                    out = feedback.save(service.cfg, str(data.get("kind", "")), data.get("text"))
                except ValueError as e:
                    return self._send(400, {"ok": False, "error": str(e)})
                if data.get("mail") is True and out["mailto"]:
                    import os

                    try:
                        if sys.platform == "darwin":
                            import subprocess

                            subprocess.Popen(["open", out["mailto"]])
                        else:
                            os.startfile(out["mailto"])  # opens a draft in the user's mail program; nothing is sent
                    except OSError:
                        out["error"] = "no mail program is set up - the note is saved as a file"
                return self._send(200, out)
            if self.path == "/warm":  # you started talking or typing: have the connections open when you finish
                from . import speed

                return self._send(200, {"ok": True, "warming": speed.warm(service.cfg)})
            if self.path == "/ollama/pull":  # download the local model through the user's own Ollama (no terminal)
                from . import modelpull

                origin = self.headers.get("Origin", "")
                if origin and not origin.startswith(LOCAL_ORIGINS):
                    return self._send(403, {"error": "only the app itself may start a download"})
                choice = data.get("model") if isinstance(data.get("model"), str) else None
                got = modelpull.start(service.cfg, choice)
                return self._send(200, {"ok": not got.get("error") or got.get("running"), **got})
            if self.path in ("/key", "/settings"):
                from . import settings

                origin = self.headers.get("Origin", "")
                if origin and not origin.startswith(LOCAL_ORIGINS):
                    return self._send(403, {"error": "only the app itself may change settings"})
                if self.path == "/key":  # one way only: into the encrypted vault. Nothing here ever returns a key.
                    name = str(data.get("name", ""))
                    if data.get("delete") is True:
                        return self._send(200, {"ok": settings.delete_key(name), "keys": settings.keys()})
                    try:
                        problem = settings.set_key(name, data.get("value"))
                    except Exception as e:
                        problem = f"could not store the key ({type(e).__name__})"
                    return self._send(400 if problem else 200, {"ok": not problem, "error": problem,
                                                                "keys": settings.keys()})
                changed, problem = settings.apply(service.cfg, data.get("changes"))
                return self._send(400 if problem else 200, {"ok": not problem, "error": problem, "changed": changed,
                                                            "settings": settings.snapshot(service.cfg)})
            if self.path == "/open" and isinstance(data.get("path"), str):
                from . import company

                u = company.user() if company.enabled() else None
                if u and u["role"] != "owner" and Path(data["path"]).parent.name.lower() == "attachments":
                    # an attached file opens in Office / a viewer in the OWNER's Windows session: colleagues preview
                    # attachments inside the app (/file) instead
                    return self._send(403, {"ok": False, "error": "attachments open in the app's preview"})
                ok, why = open_created(service.cfg, data["path"], reveal=bool(data.get("reveal")))
                return self._send(200 if ok else 403, {"ok": ok, "error": why})
            if self.path == "/voice" and isinstance(data.get("voice"), dict):
                from . import tts

                cfg = config.Config.load()
                if data.get("engine") in ("auto", "piper", "sapi", "elevenlabs"):
                    cfg.tts_engine = data["engine"]
                    service.cfg.tts_engine = cfg.tts_engine
                cfg.voice = tts.normalize(data["voice"])
                cfg.save()
                service.cfg.voice = cfg.voice
                return self._send(200, {"voice": cfg.voice, "engines": tts.engines_status()})
            if self.path == "/library":  # add / remove / refresh a folder of Settings > Your folders
                from . import library
                from .security.policy import PolicyError

                origin = self.headers.get("Origin", "")
                if origin and not origin.startswith(LOCAL_ORIGINS):
                    return self._send(403, {"error": "only the app itself may change the library"})
                action, path = data.get("action"), data.get("path", "")
                if not isinstance(path, str) or len(path) > 1000:
                    return self._send(400, {"error": "bad folder"})
                try:
                    if action == "add":
                        result = library.add(service.cfg, path)
                    elif action == "remove":
                        result = {"removed": library.remove(path)}
                    elif action == "refresh":
                        result = {"folders": library.refresh(service.cfg)}
                    else:
                        return self._send(400, {"error": "unknown action"})
                except (library.LibraryError, PolicyError) as e:
                    return self._send(400, {"error": str(e)})
                return self._send(200, {"ok": True, "result": result, "folders": library.folders()})
            if self.path == "/calendar":
                from . import calendar_api

                origin = self.headers.get("Origin", "")
                if origin and not origin.startswith(LOCAL_ORIGINS):
                    return self._send(403, {"error": "only the app itself may change the calendar"})
                ok, body = calendar_api.act(service.cfg, data)
                return self._send(200 if ok else 400, body)
            if self.path == "/deals":
                from . import deals_api

                origin = self.headers.get("Origin", "")
                if origin and not origin.startswith(LOCAL_ORIGINS):
                    return self._send(403, {"error": "only the app itself may change deals"})
                ok, body = deals_api.act(service.cfg, data)
                return self._send(200 if ok else 400, body)
            if self.path == "/quotes":
                from . import quotes_api

                origin = self.headers.get("Origin", "")
                if origin and not origin.startswith(LOCAL_ORIGINS):
                    return self._send(403, {"error": "only the app itself may change quotes"})
                ok, body = quotes_api.act(service.cfg, data)
                return self._send(200 if ok else 400, body)
            if self.path in ("/recurring", "/payment-reminders"):
                from . import clientpay_api

                origin = self.headers.get("Origin", "")
                if origin and not origin.startswith(LOCAL_ORIGINS):
                    return self._send(403, {"error": "only the app itself may change invoices and reminders"})
                ok, body = (clientpay_api.recurring_act if self.path == "/recurring" else clientpay_api.reminders_act)(
                    service.cfg, data)
                return self._send(200 if ok else 400, body)
            if self.path == "/budget":
                from . import budget_api

                origin = self.headers.get("Origin", "")
                if origin and not origin.startswith(LOCAL_ORIGINS):
                    return self._send(403, {"error": "only the app itself may change the budget"})
                ok, body = budget_api.act(data, service.cfg)
                return self._send(200 if ok else 400, body)
            if self.path == "/bills":
                from . import bills_api

                origin = self.headers.get("Origin", "")
                if origin and not origin.startswith(LOCAL_ORIGINS):
                    return self._send(403, {"error": "only the app itself may change bills and invoices"})
                ok, body = bills_api.act(service.cfg, data)
                return self._send(200 if ok else 400, body)
            if self.path == "/chats":
                from . import conversation

                action, cid = data.get("action"), str(data.get("id", ""))
                switches = action in ("new", "open") or (action == "delete" and cid == conversation.current())
                if switches and service.open_jobs():
                    # a running task writes its answer into the open chat: it must not land in another one
                    return self._send(409, {"ok": False, "error": "wait for the running tasks to finish first"})
                if action == "new":
                    ok = bool(conversation.new())
                elif action == "open":
                    ok = conversation.open_chat(cid)
                elif action == "delete":
                    ok = conversation.delete(cid)
                elif action == "rename":
                    ok = conversation.rename(cid, str(data.get("title", "")))
                else:
                    return self._send(400, {"ok": False, "error": "unknown action"})
                if ok and switches and service._agent is not None:
                    service._agent.history[:] = conversation.load(12)  # in place: every fork shares this list
                now = conversation.current()
                return self._send(200 if ok else 404, {"ok": ok, "chats": conversation.chats(), "current": now,
                                                       "messages": conversation.messages(now) or []})
            if self.path == "/history/clear":
                from . import conversation

                conversation.clear()
                if service._agent is not None:
                    del service._agent.history[:]  # in place: running tasks share this very list
                return self._send(200, {"ok": True})
            if self.path == "/tts" and isinstance(data.get("text"), str):
                from . import tts

                if len(data["text"]) > 1500:  # the app speaks sentence by sentence (and at most ~600 characters)
                    return self._send(413, {"error": "too much text to speak at once"})
                preview = data.get("voice") if isinstance(data.get("voice"), dict) else None
                try:
                    if data.get("stream") is True:  # the app can play audio while it arrives: the cloud voice streams
                        from . import voicestream

                        voiced = voicestream.speak(data["text"], voice=preview)
                        if voiced.chunks is not None:
                            return self._stream_pcm(voiced)
                        wav = voiced.wav
                    else:
                        wav = tts.synthesize(data["text"], voice=preview)
                except Exception as e:
                    return self._send(503, {"error": str(e)})
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                origin = self.headers.get("Origin", "")
                if origin.startswith(LOCAL_ORIGINS):
                    self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Content-Length", str(len(wav)))
                self.end_headers()
                self.wfile.write(wav)
                return
            if self.path == "/approve":
                job = service.jobs.get(str(data.get("job")))
                return self._send(200, {"ok": bool(job) and self._mine(job) and service.approve(
                    str(data.get("job")), data.get("allow") is True, str(data.get("card", "")))})
            self._send(404, {"error": "not found"})

    return H


def serve(cfg, port: int | None = None, service: Service | None = None):
    port = cfg.api_port if port is None else port
    token = get_token()
    from . import tts
    from .security import audit, integrity

    ok, problems = integrity.verify_code()
    INTEGRITY["ok"], INTEGRITY["problems"] = ok, problems[:10]
    if not ok:
        audit.log("integrity_failed", problems=problems[:20])
        try:  # the windowed app has no console: say it where the owner sees it (and in Settings, see settings.warnings)
            from . import reminders

            reminders.notify("Vaelon - code changed", "Vaelon's code was changed outside approved updates. "
                             "Open Vaelon to see what changed.", "warning")
        except Exception:
            pass
        lines = "\n  ".join(problems[:10])
        print(f"WARNING: Vaelon's code changed outside approved self-modification:\n  {lines}\n"
              "If YOU made these edits: vaelon integrity sign")
    tts.warmup(wait=4.0)  # after the window is up: the voices must not slow the start down
    from . import reminders

    reminders.watch(cfg=cfg)  # fires reminders: a Windows notification + a notice in the app
    service = service or Service(cfg)
    try:
        service.agent().warmup()  # model in RAM + prompt cached before the first question
    except Exception:
        pass
    from . import company

    company.start_session()  # company mode: the owner is signed in on the owner's PC unless "lock on start" is set
    srv = _Server(("127.0.0.1", port), make_handler(service, token, port))
    try:  # real-time voice bridge (opt-in in the app; needs a Gemini key and the websockets package)
        from . import live

        live.start(service, token, srv.server_address[1] + 1)
    except Exception:
        pass
    print(f"Vaelon API on http://127.0.0.1:{srv.server_address[1]}  (token file: {config.HOME / 'api_token'})")
    return srv
