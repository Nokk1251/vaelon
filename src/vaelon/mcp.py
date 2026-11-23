"""MCP connections: Vaelon can use tools offered by outside programs and services that speak the
Model Context Protocol (https://modelcontextprotocol.io) - the common standard for plugging tools into AI agents.

This is Vaelon's own client (JSON-RPC over stdio or Streamable HTTP); no SDK is needed. It speaks both
generations of the protocol and finds out by itself which one a server uses:
- modern (2026-07-28): no handshake - every request carries its protocol version in `_meta`;
- legacy (2025-11-25 and earlier): an `initialize` handshake first, sessions on HTTP.
Not supported: the deprecated HTTP+SSE transport of 2024, OAuth sign-in, and servers asking Vaelon for input
(sampling / elicitation) - Vaelon declares no client capabilities, so a server may not rely on them.

An MCP server is somebody else's program. The safety rules:
- Only YOU add a server (`vaelon mcp add`): you see the exact command or address and every tool, then confirm.
  The model has no tool that adds, edits or enables servers, and file tools cannot reach ~/.vaelon/mcp.
- A server's file is fingerprinted like a plugin (security/integrity.py): edited by anything else, it is ignored.
- Every tool is PINNED: name + description + argument schema are hashed when you approve them. A server that
  later changes a tool (a "rug pull") gets that tool blocked until you run `vaelon mcp refresh`.
- Tool descriptions are outside text that reaches the model: they are cleaned and shortened, and a tool whose
  description reads like instructions to the model is not offered at all.
- Every call needs your approval (the tools are DANGEROUS: your data leaves Vaelon). `vaelon mcp allow` lifts
  that for one tool - never for a task that already read outside content. Results are fenced as untrusted data.
- A local server starts without your API keys in its environment; it gets only the keys you named with --env.
  Keys of model providers are never handed to an MCP server (providers.KEY_HOSTS).
- Nothing starts with Vaelon: a server is launched the first time one of its tools is used.
"""
from __future__ import annotations

import atexit
import base64
import hashlib
import json
import re
import shutil
import subprocess
import os
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from . import __version__, config
from .security import audit, integrity
from .security.injection import fence, scan
from .security.policy import Risk

MODERN = "2026-07-28"
LEGACY = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")  # newest first
MODERN_ERRORS = (-32020, -32021, -32022)  # header mismatch, missing client capability, unsupported version
KIND = "mcp"
CLIENT = {"name": "vaelon", "version": __version__}
META = "io.modelcontextprotocol/"
def _mcp_summary(server: str, tool: str, args) -> str:
    """The approval card: the WHOLE argument text (a long one is shown in full, never cut silently)."""
    text = json.dumps(args, ensure_ascii=False, default=str, indent=1)
    if len(text) > 4000:
        text = text[:4000] + f"\n... and {len(text) - 4000} more characters (deny if you cannot check them)"
    return f"Use '{tool}' of the MCP server '{server}' with:\n{text}\nThis is sent to that server."


LINE_MAX = 8_000_000  # one stdio protocol message at most (a server that never ends a line cannot fill the memory)
PROBE_TIMEOUT = 10.0   # how long a server gets to answer the "which generation are you" question
START_TIMEOUT = 90.0   # first answer of a freshly started server (npx may download it first)
CALL_TIMEOUT = 120.0
MAX_TOOLS = 60         # per server
MAX_BYTES = 2_000_000  # per answer
LOOPBACK = ("127.0.0.1", "localhost", "::1")
SERVER_RX = re.compile(r"[a-z][a-z0-9]{1,19}")
TOOL_RX = re.compile(r"[A-Za-z0-9_.\-]{1,64}")
ARG_RX = re.compile(r"[A-Za-z0-9_.\-]{1,48}")
TOKEN_RX = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")  # RFC 9110 field-name


class McpError(Exception):
    """Anything that goes wrong talking to a server. `code` is the JSON-RPC error code when the server sent one;
    `http` is the HTTP status when the answer was not a JSON-RPC message at all."""

    def __init__(self, message: str, code: int | None = None, data=None, http: int | None = None):
        super().__init__(message)
        self.code, self.data, self.http = code, data, http


# ---------------------------------------------------------------- transports

class _Stdio:
    """A local server: a child process; one JSON-RPC message per line on its stdin/stdout."""

    def __init__(self, command: list[str], env: dict):
        exe = shutil.which(command[0]) or command[0]  # npx is npx.cmd on Windows
        try:
            self.proc = subprocess.Popen([exe, *command[1:]], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, env=env,
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                         start_new_session=sys.platform != "win32")  # its own group: stopped whole
        except OSError as e:
            raise McpError(f"cannot start '{command[0]}': {e.strerror or e}")
        self._cond = threading.Condition()
        self._answers: dict = {}
        self._pending: set = set()  # ids of requests sent and not yet answered: other answers are dropped
        self._write = threading.Lock()
        self.dead = False
        self.log = ""  # the last lines the server wrote to stderr (shown when it dies)
        threading.Thread(target=self._read, daemon=True, name="mcp-read").start()
        threading.Thread(target=self._drain, daemon=True, name="mcp-log").start()

    def _read(self) -> None:
        try:
            while True:
                raw = self.proc.stdout.readline(LINE_MAX)
                if not raw:
                    break
                if not raw.endswith(b"\n") and len(raw) >= LINE_MAX:  # over-long: skip the rest of that line
                    while True:
                        more = self.proc.stdout.readline(LINE_MAX)
                        if not more or more.endswith(b"\n"):
                            break
                    continue
                try:
                    msg = json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    continue  # not a protocol message (a badly behaved server printing to stdout)
                if not isinstance(msg, dict):
                    continue
                if "method" in msg:
                    if "id" in msg:  # legacy servers may ask the client things: only `ping` is answered
                        ok = msg["method"] == "ping"
                        self._put({"jsonrpc": "2.0", "id": msg["id"], **({"result": {}} if ok else {
                            "error": {"code": -32601, "message": "Vaelon does not offer this to servers"}})})
                    continue  # notifications (progress, logs) are not needed
                if "id" in msg:
                    with self._cond:
                        if msg["id"] in self._pending:
                            self._answers[msg["id"]] = msg
                        self._cond.notify_all()
        except (OSError, ValueError):
            pass
        with self._cond:
            self.dead = True
            self._cond.notify_all()

    def _drain(self) -> None:
        try:
            for raw in self.proc.stderr:
                self.log = (self.log + raw.decode("utf-8", "replace"))[-600:]
        except (OSError, ValueError):
            pass

    def _put(self, msg: dict) -> None:
        data = (json.dumps(msg, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        with self._write:
            self.proc.stdin.write(data)
            self.proc.stdin.flush()

    def _gone(self) -> McpError:
        from .security import dlp

        tail = " ".join(self.log.split())[-200:]
        return McpError("the server program stopped" + (f" ({dlp.scrub(tail)})" if tail else ""))

    def send(self, msg: dict) -> None:
        if "method" in msg and "id" in msg:
            with self._cond:
                self._pending.add(msg["id"])
        try:
            self._put(msg)
        except (OSError, ValueError):
            raise self._gone()

    def wait(self, ids: list, timeout: float) -> dict | None:
        """The answer to one of `ids`, or None when the time is up."""
        end = time.monotonic() + timeout
        with self._cond:
            while True:
                for i in ids:
                    if i in self._answers:
                        self._pending.discard(i)
                        return self._answers.pop(i)
                if self.dead:
                    raise self._gone()
                left = end - time.monotonic()
                if left <= 0:
                    return None
                self._cond.wait(left)

    def alive(self) -> bool:
        return not self.dead and self.proc.poll() is None

    def close(self) -> None:
        """The protocol's shutdown: close stdin, give the server a moment, then stop it (our own child, by handle)."""
        try:
            self.proc.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            self.proc.wait(2)
        except subprocess.TimeoutExpired:
            if sys.platform == "win32":  # `npx` is cmd.exe -> node: stop the whole tree of OUR child, by its PID
                subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                import signal

                try:
                    os.killpg(self.proc.pid, signal.SIGTERM)  # started in its own session (see Stdio.__init__)
                except OSError:
                    pass
            self.proc.terminate()
            try:
                self.proc.wait(2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(5)
        for stream in (self.proc.stdout, self.proc.stderr):
            try:
                stream.close()
            except (OSError, ValueError):
                pass


class _Http:
    """A remote (or local) server at one address: every message is its own POST; the answer is JSON or an SSE stream."""

    def __init__(self, url: str, headers: dict):
        self.url, self.base, self.session = url, headers, None

    def post(self, msg: dict, headers: dict, timeout: float) -> dict | None:
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **self.base, **headers}
        if self.session:
            h["Mcp-Session-Id"] = self.session  # legacy servers only
        try:
            r = requests.post(self.url, data=json.dumps(msg).encode("utf-8"), headers=h, timeout=(10, timeout),
                              allow_redirects=False, stream=True)  # no redirects: a key must not follow one
        except requests.RequestException as e:
            raise McpError(f"cannot reach the server ({type(e).__name__})")
        with r:
            if r.headers.get("Mcp-Session-Id"):
                self.session = r.headers["Mcp-Session-Id"]
            if "id" not in msg:
                return None  # a notification: nothing comes back
            try:
                if "text/event-stream" in r.headers.get("Content-Type", ""):
                    return self._stream(r, msg["id"])
                body = r.raw.read(MAX_BYTES + 1, decode_content=True)
            except (requests.RequestException, OSError) as e:
                raise McpError(f"the connection broke ({type(e).__name__})")
            if len(body) > MAX_BYTES:
                raise McpError("the answer is too large")
            try:
                obj = json.loads(body.decode("utf-8", "replace"))
            except ValueError:
                obj = None
            if isinstance(obj, dict) and ("result" in obj or "error" in obj):
                return obj
            raise McpError(f"the server answered HTTP {r.status_code} without a protocol message", http=r.status_code)

    @staticmethod
    def _lines(r, deadline: float):
        """Lines of an event stream with a cap on the total size and an overall deadline (keep-alive comments every
        few seconds must not keep a call open for ever)."""
        buf, size = b"", 0
        for chunk in r.iter_content(8192):
            size += len(chunk)
            if size > MAX_BYTES:
                raise McpError("the answer is too large")
            if time.monotonic() > deadline:
                raise McpError("no answer in time")
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                yield line.rstrip(b"\r")
        if buf:
            yield buf

    @classmethod
    def _stream(cls, r, want, timeout: float = CALL_TIMEOUT) -> dict:
        from .tools.web import cutter

        watchdog = threading.Timer(timeout + 5, cutter(r))  # a read that hangs inside one chunk is cut too
        watchdog.daemon = True
        watchdog.start()
        try:
            return cls._events(r, want, timeout)
        finally:
            watchdog.cancel()

    @classmethod
    def _events(cls, r, want, timeout: float) -> dict:
        data = []
        for line in cls._lines(r, time.monotonic() + timeout):
            text = line.decode("utf-8", "replace")
            if text.startswith("data:"):
                data.append(text[5:].lstrip(" "))
            elif not text and data:  # a blank line ends one event
                try:
                    obj = json.loads("\n".join(data))
                except ValueError:
                    obj = None
                data = []
                if isinstance(obj, dict) and obj.get("id") == want and ("result" in obj or "error" in obj):
                    return obj  # progress notifications before it are skipped
        raise McpError("the stream ended without an answer")

    def alive(self) -> bool:
        return True

    def close(self) -> None:
        self.session = None


# ---------------------------------------------------------------- the client

class Client:
    """One connection to one server. Thread-safe: parallel tasks may call tools of the same server."""

    def __init__(self, name: str, spec: dict):
        self.name, self.spec = name, spec
        self._lock = threading.RLock()
        self._t: _Stdio | _Http | None = None
        self._id = 0
        self._defs: dict | None = None
        self.modern, self.version = True, MODERN

    def _next(self) -> int:
        with self._lock:
            self._id += 1
            return self._id

    def _open(self):
        from .security import dlp

        spec = self.spec
        if spec.get("url"):
            check_url(spec["url"])
            headers = {}
            if spec.get("key"):
                headers["Authorization"] = "Bearer " + _secret(spec["key"])
            return _Http(spec["url"], headers)
        env = dlp.safe_env()  # none of your stored keys ...
        for var, key_name in (spec.get("env") or {}).items():
            env[var] = _secret(key_name)  # ... except the ones you named for this server
        return _Stdio(list(spec["command"]), env)

    def _message(self, method: str, params: dict | None) -> dict:
        params = dict(params or {})
        if self.modern:
            params["_meta"] = {META + "protocolVersion": self.version, META + "clientInfo": CLIENT,
                               META + "clientCapabilities": {}}
        return {"jsonrpc": "2.0", "id": self._next(), "method": method, "params": params}

    def _headers(self, method: str, params: dict, schema: dict | None = None) -> dict:
        if not isinstance(self._t, _Http):
            return {}
        if not self.modern:
            return {"MCP-Protocol-Version": self.version} if self.version >= "2025-06-18" else {}
        h = {"MCP-Protocol-Version": self.version, "Mcp-Method": method}
        if method == "tools/call":
            h["Mcp-Name"] = header_value(str(params.get("name", "")))
            h.update(param_headers(schema or {}, params.get("arguments") or {}))
        return h

    def _exchange(self, msg: dict, headers: dict, timeout: float, also: list | None = None) -> dict | None:
        t = self._t
        if isinstance(t, _Http):
            return t.post(msg, headers, timeout)
        t.send(msg)
        return t.wait([msg["id"], *(also or [])], timeout)

    def _rpc(self, method: str, params: dict | None = None, timeout: float = CALL_TIMEOUT, schema=None) -> dict:
        msg = self._message(method, params)
        answer = self._exchange(msg, self._headers(method, msg["params"], schema), timeout)
        if answer is None:
            if isinstance(self._t, _Stdio):  # tell the server to stop working on it
                try:
                    self._t.send({"jsonrpc": "2.0", "method": "notifications/cancelled",
                                  "params": {"requestId": msg["id"], "reason": "timeout"}})
                except McpError:
                    pass
            raise McpError(f"no answer within {int(timeout)} s")
        return _result(answer)

    def connect(self) -> None:
        with self._lock:
            if self._t is not None and self._t.alive():
                return
            self.close()
            self._t, self.modern, self.version = self._open(), True, MODERN
            try:
                self._detect()
            except BaseException:
                self.close()
                raise

    def _detect(self) -> None:
        """Which generation is this server? Ask the modern way first (`server/discover`); a server that does not
        know the question - any error that is not a modern one, or silence - gets the old handshake."""
        probe = self._message("server/discover", None)
        try:
            answer = self._exchange(probe, self._headers("server/discover", {}), PROBE_TIMEOUT)
        except McpError as e:
            if e.http is None:
                raise  # unreachable / the program died: not a question of generations
            answer = {"error": {"code": None, "message": str(e)}}
        late = [probe["id"]] if answer is None else []  # slow start: the probe may still be answered
        if answer is not None and self._settle(answer):
            return
        self.modern = False
        init = {"jsonrpc": "2.0", "id": self._next(), "method": "initialize",
                "params": {"protocolVersion": LEGACY[0], "capabilities": {}, "clientInfo": CLIENT}}
        deadline = time.monotonic() + START_TIMEOUT
        reply = self._exchange(init, {}, START_TIMEOUT, late)
        while reply is not None and reply.get("id") != init["id"]:  # the late probe answer came first
            if self._settle(reply):
                self.modern = True
                return
            reply = self._t.wait([init["id"]], max(1.0, deadline - time.monotonic()))
        if reply is None:
            raise McpError(f"the server did not answer within {int(START_TIMEOUT)} s")
        version = str(_result(reply).get("protocolVersion") or "")
        if version not in LEGACY:
            raise McpError(f"the server speaks protocol '{version or '?'}', which Vaelon does not know")
        self.version = version
        note = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        if isinstance(self._t, _Http):
            self._t.post(note, self._headers("notifications/initialized", {}), 15)
        else:
            self._t.send(note)

    def _settle(self, answer: dict) -> bool:
        """True: the server is modern and Vaelon's version works. False: use the old handshake."""
        if "result" in answer:
            versions = (answer.get("result") or {}).get("supportedVersions")
        else:
            err = answer.get("error") or {}
            if err.get("code") not in MODERN_ERRORS:
                return False
            if err.get("code") != -32022:
                raise McpError(f"the server refused Vaelon: {str(err.get('message'))[:200]}", err.get("code"))
            versions = (err.get("data") or {}).get("supported") if isinstance(err.get("data"), dict) else None
        versions = [str(v) for v in versions] if isinstance(versions, list) else []
        if MODERN in versions:
            return True
        if any(v in LEGACY for v in versions):
            return False  # it also speaks an older version Vaelon knows
        raise McpError(f"the server only speaks protocol {', '.join(versions) or '?'}; Vaelon speaks {MODERN} "
                       f"and {LEGACY[-1]} to {LEGACY[0]}")

    def list_tools(self) -> list[dict]:
        self.connect()
        tools, cursor = [], None
        for _ in range(20):  # pages
            res = self._rpc("tools/list", {"cursor": cursor} if cursor else {}, START_TIMEOUT)
            tools += [t for t in res.get("tools") or [] if isinstance(t, dict)]
            cursor = res.get("nextCursor")
            if not cursor or len(tools) >= 500:
                break
        return tools

    def definitions(self) -> dict:
        """{tool name: definition} as the server offers them NOW (asked once per connection)."""
        with self._lock:
            self.connect()
            if self._defs is None:
                self._defs = {str(t.get("name")): t for t in self.list_tools()}
            return self._defs

    def call(self, tool: str, arguments: dict, schema: dict | None = None) -> dict:
        self.connect()
        try:
            return self._rpc("tools/call", {"name": tool, "arguments": arguments}, CALL_TIMEOUT, schema)
        except McpError as e:
            if e.http is not None:
                self.close()  # e.g. an expired legacy session: the next call starts fresh
            raise

    def close(self) -> None:
        with self._lock:
            t, self._t, self._defs = self._t, None, None
        if t is not None:
            t.close()


def _result(answer: dict) -> dict:
    if "error" in answer:
        err = answer.get("error") or {}
        raise McpError(str(err.get("message") or "the server reported an error")[:300], err.get("code"), err.get("data"))
    res = answer.get("result")
    return res if isinstance(res, dict) else {}


def _secret(key_name: str) -> str:
    value = config.env(key_name)
    if not value:
        raise McpError(f"the key {key_name} is not stored - run: vaelon key set {key_name}")
    return value


def check_url(url: str) -> None:
    """A server on this PC may use plain http; anything else must be https and pass the same guards as a web page."""
    u = urlparse(url)
    if (u.hostname or "").lower() in LOOPBACK and u.scheme in ("http", "https"):
        return
    if u.scheme != "https":
        raise McpError("a remote MCP server must use https")
    from .tools.web import _guard

    try:
        _guard(url)
    except ValueError as e:
        raise McpError(str(e))


# ---------------------------------------------------------------- headers mirrored from arguments (HTTP, modern)

def header_value(text: str) -> str:
    plain = all(0x20 <= ord(c) <= 0x7E or c == "\t" for c in text) and text == text.strip() \
        and not (text.startswith("=?base64?") and text.endswith("?="))
    return text if plain and text else "=?base64?" + base64.b64encode(text.encode("utf-8")).decode() + "?="


def header_plan(schema: dict) -> dict | None:
    """{argument path: header name} for the `x-mcp-header` marks in a tool's schema, or None when a mark breaks the
    standard's rules (such a tool must not be used over HTTP)."""
    plan, seen, ok = {}, set(), [True]

    def walk(node, path, direct):
        if isinstance(node, list):
            for child in node:
                walk(child, path, False)
            return
        if not isinstance(node, dict):
            return
        if "x-mcp-header" in node:
            name = node["x-mcp-header"]
            if (direct and path and isinstance(name, str) and TOKEN_RX.fullmatch(name) and name.lower() not in seen
                    and node.get("type") in ("string", "integer", "boolean")):
                seen.add(name.lower())
                plan[path] = name
            else:
                ok[0] = False
        for key, child in node.items():
            if key == "properties" and isinstance(child, dict):
                for prop, sub in child.items():
                    walk(sub, path + (prop,), direct)
            elif key != "x-mcp-header":
                walk(child, path, False)

    walk(schema, (), True)
    return plan if ok[0] else None


def param_headers(schema: dict, arguments: dict) -> dict:
    out = {}
    for path, name in (header_plan(schema) or {}).items():
        value = arguments
        for step in path:
            value = value.get(step) if isinstance(value, dict) else None
        if value is None:
            continue
        text = ("true" if value else "false") if isinstance(value, bool) else str(value)
        out["Mcp-Param-" + name] = header_value(text)
    return out


# ---------------------------------------------------------------- vetting, pinning, storing

def clean(text, limit: int) -> str:
    """Outside text that will sit in the model's prompt: one line, no control characters or tag brackets, short."""
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f<>]", " ", str(text or ""))).strip()[:limit]


def _texts(node) -> list[str]:
    """Every human-language string of a tool definition (descriptions and titles, however deep)."""
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("description", "title") and isinstance(v, str):
                out.append(v)
            else:
                out += _texts(v)
    elif isinstance(node, list):
        for v in node:
            out += _texts(v)
    return out


def vet(tool: dict, http: bool = False) -> str | None:
    """Why a tool a server offers must NOT be given to the model (None = fine)."""
    name, schema = tool.get("name"), tool.get("inputSchema")
    if not isinstance(name, str) or not TOOL_RX.fullmatch(name):
        return "its name is not a plain identifier"
    if not isinstance(schema, dict):
        return "it has no argument schema"
    props = schema.get("properties") or {}
    if not isinstance(props, dict) or not all(isinstance(k, str) and ARG_RX.fullmatch(k) for k in props):
        return "an argument name is not a plain identifier"
    if len(json.dumps(tool, default=str)) > 12000:
        return "its definition is too large"
    if any(scan(text) for text in _texts(tool)):
        return "its description reads like instructions to the model (prompt injection)"
    if http and header_plan(schema) is None:
        return "its header annotations break the standard"
    return None


def fingerprint(tool: dict) -> str:
    body = {"name": tool.get("name"), "description": tool.get("description"), "inputSchema": tool.get("inputSchema")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def validate(name: str, spec: dict) -> None:
    from .providers import KEY_HOSTS

    if not SERVER_RX.fullmatch(name or ""):
        raise McpError("server name: 2-20 lowercase letters or digits, starting with a letter (e.g. files, github)")
    command, url = spec.get("command"), spec.get("url")
    if bool(command) == bool(url):
        raise McpError("give either a command to run (after --) or --url")
    if command and not (isinstance(command, list) and all(isinstance(c, str) and c for c in command)):
        raise McpError("the command must be a list of words")
    if url:
        check_url(url)
    keys = list((spec.get("env") or {}).values()) + ([spec["key"]] if spec.get("key") else [])
    for var in spec.get("env") or {}:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", var):
            raise McpError(f"'{var}' is not a valid environment variable name")
    for key_name in keys:
        if not re.fullmatch(r"[A-Z0-9_]{2,64}", str(key_name)):
            raise McpError(f"'{key_name}' is not a key NAME (keys are stored with: vaelon key set NAME)")
        if key_name in KEY_HOSTS:
            raise McpError(f"{key_name} belongs to {KEY_HOSTS[key_name]} and is never given to another program")


def folder() -> Path:
    return config.HOME / "mcp"


def _file(name: str) -> Path:
    return folder() / f"{name}.json"


def load(name: str) -> dict | None:
    """A server's settings - only if the file is exactly what the owner approved."""
    f = _file(name)
    if not SERVER_RX.fullmatch(name or "") or not f.is_file() or not integrity.is_trusted(KIND, f):
        return None
    try:
        spec = json.loads(f.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return spec if isinstance(spec, dict) else None


def names() -> list[str]:
    return sorted(f.stem for f in folder().glob("*.json")) if folder().is_dir() else []


def servers() -> dict[str, dict]:
    out = {}
    for name in names():
        spec = load(name)
        if spec is None:
            audit.log("mcp_untrusted_skipped", server=name)
        else:
            out[name] = spec
    return out


def save(name: str, spec: dict) -> None:
    """Store a server and approve this exact content. Called only from the owner's own commands."""
    validate(name, spec)
    folder().mkdir(parents=True, exist_ok=True)
    tmp = _file(name).with_suffix(".tmp")
    tmp.write_text(json.dumps(spec, indent=1, ensure_ascii=False, sort_keys=True), "utf-8")
    tmp.replace(_file(name))
    integrity.trust(KIND, _file(name))
    drop(name)


def remove(name: str) -> bool:
    drop(name)
    f = _file(name)
    if not f.is_file():
        return False
    f.unlink()
    return True


def inspect(name: str, spec: dict) -> tuple[dict, list[tuple[str, str]]]:
    """Connect once and look at what the server offers: (tools fit to pin, [(tool, why not)])."""
    validate(name, spec)
    client = Client(name, spec)
    try:
        listed = client.list_tools()
    finally:
        client.close()
    good, bad = {}, []
    for t in listed:
        why = vet(t, http=bool(spec.get("url")))
        label = clean(t.get("name"), 40) or "?"
        if why is None and tool_id(name, t["name"]) in {tool_id(name, g) for g in good}:
            why = "its name collides with another tool"
        if why is None and len(good) >= MAX_TOOLS:
            why = f"more than {MAX_TOOLS} tools"
        if why:
            bad.append((label, why))
        else:
            good[t["name"]] = {"description": str(t.get("description") or ""), "inputSchema": t["inputSchema"],
                               "sha": fingerprint(t)}
    return good, bad


# ---------------------------------------------------------------- the tools the model sees

_clients: dict[str, tuple[str, Client]] = {}
_registered: set[str] = set()
_guard_lock = threading.Lock()


def tool_id(server: str, tool: str) -> str:
    return f"mcp_{server}_" + re.sub(r"[^a-z0-9]+", "_", tool.lower()).strip("_")[:40]


def _client(server: str, spec: dict) -> Client:
    where = json.dumps([spec.get("command"), spec.get("url"), spec.get("env"), spec.get("key")], sort_keys=True)
    with _guard_lock:
        have = _clients.get(server)
        if have and have[0] == where:
            return have[1]
        _clients[server] = (where, Client(server, spec))
    if have:
        have[1].close()
    return _clients[server][1]


def drop(server: str | None = None) -> None:
    """Close the connection to one server (or to all: at exit)."""
    with _guard_lock:
        gone = [_clients.pop(n) for n in ([server] if server else list(_clients)) if n in _clients]
    for _, client in gone:
        try:
            client.close()
        except Exception:
            pass


atexit.register(drop)


def coerce(schema: dict, args: dict) -> dict:
    """Models hand over every argument as text; servers validate types. Turn "5" into 5 where the schema says so."""
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    out = {}
    for k, v in args.items():
        kind = (props.get(k) or {}).get("type") if isinstance(props.get(k), dict) else None
        if isinstance(kind, list):
            kind = next((x for x in kind if x != "null"), None)
        if isinstance(v, str):
            s = v.strip()
            try:
                if kind == "integer":
                    v = int(s)
                elif kind == "number":
                    v = float(s) if any(c in s for c in ".eE") else int(s)
                elif kind == "boolean" and s.lower() in ("true", "false", "yes", "no", "1", "0"):
                    v = s.lower() in ("true", "yes", "1")
                elif kind in ("array", "object"):
                    v = json.loads(s)
            except ValueError:
                pass  # let the server say what is wrong
        out[k] = v
    return out


def render(res: dict) -> tuple[str, bool]:
    """(text for the model, did the tool report a failure)."""
    kind = res.get("resultType", "complete")
    if kind == "input_required":
        return "the server asked Vaelon for extra input; Vaelon does not hand that to outside servers", True
    if kind != "complete":
        return f"the server sent an unknown kind of result ({clean(kind, 40)})", True
    parts = []
    for item in res.get("content") or []:
        if not isinstance(item, dict):
            continue
        t = item.get("type")
        if t == "text":
            parts.append(str(item.get("text", "")))
        elif t in ("image", "audio"):
            size = len(str(item.get("data", ""))) * 3 // 4
            parts.append(f"[{t} {clean(item.get('mimeType'), 40)}, {size} bytes - not shown]")
        elif t == "resource_link":
            parts.append(f"[link] {clean(item.get('name'), 80)} {clean(item.get('uri'), 300)}")
        elif t == "resource":
            r = item.get("resource") if isinstance(item.get("resource"), dict) else {}
            parts.append(str(r.get("text") or f"[resource {clean(r.get('uri'), 300)}]"))
    if not parts and "structuredContent" in res:
        parts.append(json.dumps(res["structuredContent"], ensure_ascii=False, default=str))
    return "\n".join(parts).strip() or "(empty result)", bool(res.get("isError"))


def _caller(server: str, tool: str):
    def run(ctx, **args):
        spec = load(server)  # read again at every call: removed, disabled or edited since start -> no call
        pin = (spec or {}).get("tools", {}).get(tool)
        if not spec or not spec.get("enabled", True) or not pin:
            return f"BLOCKED: the MCP server '{server}' or its tool '{tool}' is no longer approved (vaelon mcp list)"
        try:
            client = _client(server, spec)
            now = client.definitions().get(tool)
            if now is None:
                return f"ERROR: the MCP server '{server}' no longer offers '{tool}' (vaelon mcp refresh {server})"
            if fingerprint(now) != pin.get("sha"):
                audit.log("mcp_tool_changed", server=server, tool=tool)
                return (f"BLOCKED: the MCP server '{server}' changed the tool '{tool}' after you approved it. "
                        f"Nothing was sent. Review it with: vaelon mcp refresh {server}")
            text, failed = render(client.call(tool, coerce(pin["inputSchema"], args), pin["inputSchema"]))
        except McpError as e:
            return f"ERROR: MCP server '{server}': {e}"
        body = fence(text, f"mcp:{server}/{tool}")[0]
        return ("ERROR: the tool reported a failure.\n" + body) if failed else body

    return run


def _params(schema: dict) -> dict:
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    out = {}
    for prop, sub in (schema.get("properties") or {}).items():
        sub = sub if isinstance(sub, dict) else {}
        kind = sub.get("type") if isinstance(sub.get("type"), str) else "value"
        note = clean(sub.get("description"), 70)
        out[prop if prop in required else "?" + prop] = f"{kind}{' - ' + note if note else ''}"
    return out


def register_all() -> list[str]:
    """Offer every approved tool of every enabled, trusted server to the agent. Starts nothing."""
    from . import router
    from .tools import registry

    for old in _registered:
        registry.REGISTRY.pop(old, None)
    _registered.clear()
    words = {"mcp"}
    for server, spec in servers().items():
        if not spec.get("enabled", True):
            continue
        words |= {server} | {str(w).lower() for w in spec.get("words") or []}
        for tool, pin in (spec.get("tools") or {}).items():
            rid = tool_id(server, tool)
            if rid in registry.REGISTRY or not isinstance(pin, dict) or not isinstance(pin.get("inputSchema"), dict):
                continue
            registry.REGISTRY[rid] = registry.Tool(
                rid, f"[outside tool, MCP server '{server}'] " + clean(pin.get("description"), 180),
                _params(pin["inputSchema"]), Risk.DANGEROUS, _caller(server, tool), untrusted=True,
                summary=(lambda a, s=server, t=tool: _mcp_summary(s, t, a)),
                group="mcp")
            _registered.add(rid)
    router._WORDS["mcp"] = sorted(w for w in words if len(w) >= 3)
    registry._describe_cache.clear()
    return sorted(_registered)
