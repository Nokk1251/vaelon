"""Live voice: a real-time spoken conversation through Google's Gemini Live API.

OPT-IN, and loud about it: while Live is on, the microphone audio streams to Google - and, with screen sharing on, a
picture of the screen every few seconds. Nothing is stored by Vaelon.

The API key never leaves the core. The app talks to a small local WebSocket bridge (127.0.0.1 only, same access key
as the API) and the bridge talks to Google:

    app  <-- ws://127.0.0.1:<port> -->  bridge (this file)  <-- wss://generativelanguage.googleapis.com -->  Gemini

The Live model only talks. Everything real - the web, files, the computer, reminders, documents, memory - is done by
Vaelon itself: the model calls ONE function, `ask_vaelon`, which runs the normal agent with all its safety rules
(approvals included) and hands back the answer to say.

Needs: pip install "vaelon[live]"  and a Gemini key:  vaelon key set GEMINI_API_KEY   (free tier works)
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import threading
import time

from . import config

try:  # optional dependency; imported here so the packaged app includes it
    import websockets
except ImportError:  # pragma: no cover
    websockets = None

HOST = "generativelanguage.googleapis.com"
URL = f"wss://{HOST}/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
LOCAL_ORIGINS = ("http://localhost:", "http://127.0.0.1:")
IN_RATE, OUT_RATE = 16000, 24000  # microphone PCM sent up, voice PCM coming back (16-bit mono)
SCREEN_EVERY = 3.0  # seconds between screen pictures while sharing is on
STATE: dict = {"port": 0, "error": ""}

INSTRUCTION = (
    "You are VAELON, {addr}'s calm, precise and capable assistant, speaking aloud. Speak the language the user "
    "speaks (Bulgarian or English) and keep answers to one to three short sentences unless asked for more.\n"
    "You can chat and answer general knowledge yourself. For ANYTHING else - live data (weather, prices, news), "
    "the web, files, the computer, reminders, memory, creating documents, images or audio, or facts that change over "
    "time - call the function ask_vaelon and pass the user's request word for word, in the language they spoke "
    "(never translate or shorten it), then tell them the result briefly. When screen sharing is on you receive "
    "pictures of the user's screen: use them to answer questions about what is on it. Never invent results and never claim you did something unless ask_vaelon returned it. "
    "If ask_vaelon says an approval is needed, tell the user to look at the small window.")

ASK = {"name": "ask_vaelon",
       "description": "Do or look up anything real: web search, live data, files, the computer, reminders, memory, "
                      "creating documents. Pass the user's request in their own words. Returns what to tell them.",
       "parameters": {"type": "OBJECT", "properties": {"request": {"type": "STRING", "description": "the user's request"}},
                      "required": ["request"]}}


def available(cfg=None) -> bool:
    """Live can run: the WebSocket library is installed and a Gemini key is stored."""
    return websockets is not None and bool(config.env("GEMINI_API_KEY"))


def setup_message(cfg) -> dict:
    return {"setup": {
        "model": "models/" + (getattr(cfg, "live_model", "") or "gemini-3.1-flash-live-preview"),
        "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {"voiceConfig": {
            "prebuiltVoiceConfig": {"voiceName": getattr(cfg, "live_voice", "") or "Charon"}}}},
        "systemInstruction": {"parts": [{"text": INSTRUCTION.format(addr=cfg.address_as)}]},
        "tools": [{"functionDeclarations": [ASK]}],
        "inputAudioTranscription": {}, "outputAudioTranscription": {}}}


def audio_message(pcm: bytes) -> dict:
    return {"realtimeInput": {"audio": {"mimeType": f"audio/pcm;rate={IN_RATE}", "data": base64.b64encode(pcm).decode()}}}


def frame_message(jpeg: bytes) -> dict:
    return {"realtimeInput": {"video": {"mimeType": "image/jpeg", "data": base64.b64encode(jpeg).decode()}}}


def text_message(text: str) -> dict:
    return {"clientContent": {"turns": [{"role": "user", "parts": [{"text": text}]}], "turnComplete": True}}


def tool_response(call_id: str, name: str, result: str) -> dict:
    return {"toolResponse": {"functionResponses": [{"id": call_id, "name": name, "response": {"result": result}}]}}


def parse(msg: dict) -> list[tuple]:
    """One message from Google -> simple events:
    ("ready",) ("audio", bytes) ("you", text) ("say", text) ("interrupted",) ("turn",) ("call", id, name, args)
    ("closing", reason)"""
    out: list[tuple] = []
    if "setupComplete" in msg:
        out.append(("ready",))
    sc = msg.get("serverContent") or {}
    for part in (sc.get("modelTurn") or {}).get("parts") or []:
        data = (part.get("inlineData") or {}).get("data")
        if data:
            out.append(("audio", base64.b64decode(data)))
    if (sc.get("inputTranscription") or {}).get("text"):
        out.append(("you", sc["inputTranscription"]["text"]))
    if (sc.get("outputTranscription") or {}).get("text"):
        out.append(("say", sc["outputTranscription"]["text"]))
    if sc.get("interrupted"):
        out.append(("interrupted",))
    if sc.get("turnComplete"):
        out.append(("turn",))
    for call in (msg.get("toolCall") or {}).get("functionCalls") or []:
        out.append(("call", str(call.get("id", "")), str(call.get("name", "")), call.get("args") or {}))
    if "goAway" in msg:
        out.append(("closing", "the session is about to end"))
    return out


def screen_jpeg(max_w: int = 1024) -> bytes:
    """A compact picture of the screen (only called while the user has screen sharing switched on)."""
    from PIL import ImageGrab

    img = ImageGrab.grab()
    if img.width > max_w:
        img = img.resize((max_w, int(img.height * max_w / img.width)))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=60)
    return buf.getvalue()


def ask_vaelon(service, request: str, screen: bool, notify) -> str:
    """Run a request through the normal agent (its own job: steps, approvals, files) and return the answer."""
    jid = service.start(request, spoken=True, screen=screen)
    job = service.jobs[jid]
    rev, tool, asked = -1, "", False
    notify({"type": "task", "job": jid, "text": request[:200]})
    while job.status != "done":
        job.wait_change(rev, 1.0)
        rev = job.rev
        if job.tool and job.tool != tool:
            tool = job.tool
            notify({"type": "tool", "name": tool})
        if job.status == "approval" and job.approval and not asked:
            asked = True
            notify({"type": "approval", "job": jid, "card": job.approval.get("id", ""),
                    "summary": job.approval.get("summary", ""), "note": job.approval.get("note", "")})
        elif job.status != "approval":
            asked = False
    if job.tool and job.tool != tool:  # a fast task can use a tool and finish between two looks: still say which
        notify({"type": "tool", "name": job.tool})
    if job.files:
        notify({"type": "files", "files": job.files})
    notify({"type": "task_done", "job": jid})
    if job.cancelled:
        return "The user cancelled this request."
    return (job.answer or "No answer.")[:1800]


async def _session(ws, service, token: str) -> None:
    """One app connection: check the access key, connect to Google, relay both ways until either side leaves."""
    origin = ws.request.headers.get("Origin", "") if getattr(ws, "request", None) else ""
    if origin and not origin.startswith(LOCAL_ORIGINS):
        return await ws.close(4403, "origin not allowed")
    from .security import proof

    # both sides prove they know the access key; the key itself never crosses the socket (another program could be
    # listening on this port - then it learns nothing it could use)
    try:
        hello = json.loads(await asyncio.wait_for(ws.recv(), 8))
    except Exception:
        return await ws.close(4400, "expected a hello first")
    if not isinstance(hello, dict) or not proof.valid_nonce(hello.get("hello")):
        return await ws.close(4401, "unauthorized")
    mine = proof.nonce()
    await ws.send(json.dumps({"type": "challenge", "proof": proof.proof(token, "vaelon-live-server", hello["hello"]),
                              "nonce": mine}))
    try:
        answer = json.loads(await asyncio.wait_for(ws.recv(), 8))
    except Exception:
        return await ws.close(4401, "unauthorized")
    if not isinstance(answer, dict) or not proof.check(token, "vaelon-live-client", mine, answer.get("proof")):
        return await ws.close(4401, "unauthorized")
    from . import company

    if company.enabled() and not company.user():
        await ws.send(json.dumps({"type": "error", "text": "Vaelon is locked - sign in in the app first"}))
        return await ws.close(4423, "locked")
    if company.user() and company.user()["role"] != "owner":  # the owner's Gemini key, microphone and screen
        await ws.send(json.dumps({"type": "error", "text": "Live voice is the owner's"}))
        return await ws.close(4403, "owner only")
    started_epoch = company.epoch()
    key = config.env("GEMINI_API_KEY")
    if not key:
        await ws.send(json.dumps({"type": "error", "text": "No Gemini key stored. Run: vaelon key set GEMINI_API_KEY"}))
        return await ws.close(4000, "no key")
    cfg = config.Config.load()
    state = {"screen": bool(hello.get("screen")), "drop": False, "jobs": set()}
    loop = asyncio.get_running_loop()

    def notify(obj: dict) -> None:  # callable from worker threads
        asyncio.run_coroutine_threadsafe(ws.send(json.dumps(obj, ensure_ascii=False)), loop)

    try:
        up = await websockets.connect(f"{URL}?key={key}", max_size=None, open_timeout=20)
    except Exception as e:
        await ws.send(json.dumps({"type": "error", "text": "Could not reach Gemini Live: " + str(e).replace(key, "<key>")[:160]}))
        return await ws.close(4502, "upstream failed")

    async def run_call(call_id: str, name: str, args: dict) -> None:
        if name != "ask_vaelon":
            result = f"ERROR: unknown function {name}"
        else:
            request = str(args.get("request", "")).strip()

            def tracked(obj: dict) -> None:
                if obj.get("type") == "task":
                    state["jobs"].add(obj["job"])
                elif obj.get("type") == "task_done":
                    state["jobs"].discard(obj["job"])
                notify(obj)

            result = await loop.run_in_executor(None, ask_vaelon, service, request, state["screen"], tracked) \
                if request else "ERROR: empty request"
        try:
            await up.send(json.dumps(tool_response(call_id, name, result), ensure_ascii=False))
        except Exception:
            pass

    async def from_app() -> None:
        async for raw in ws:
            if isinstance(raw, (bytes, bytearray)):
                if raw:
                    await up.send(json.dumps(audio_message(bytes(raw))))
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if "screen" in msg:
                state["screen"] = bool(msg["screen"])
            if msg.get("stop"):  # stop talking + cancel what is being worked on
                state["drop"] = True
                for jid in list(state["jobs"]):
                    service.cancel(jid)
            if isinstance(msg.get("text"), str) and msg["text"].strip():
                await up.send(json.dumps(text_message(msg["text"].strip()[:2000]), ensure_ascii=False))

    async def from_google() -> None:
        async for raw in up:
            for ev in parse(json.loads(raw)):
                kind = ev[0]
                if kind == "audio":
                    if not state["drop"]:
                        await ws.send(ev[1])
                elif kind == "call":
                    asyncio.create_task(run_call(ev[1], ev[2], ev[3]))
                elif kind in ("you", "say"):
                    if kind == "you":
                        state["drop"] = False  # the user speaks again: listen to the new answer
                    await ws.send(json.dumps({"type": kind, "text": ev[1]}, ensure_ascii=False))
                elif kind == "turn":
                    state["drop"] = False
                    await ws.send(json.dumps({"type": "turn"}))
                elif kind == "interrupted":
                    await ws.send(json.dumps({"type": "interrupted"}))
                elif kind == "ready":
                    await ws.send(json.dumps({"type": "ready", "model": setup["setup"]["model"].split("/")[-1]}))
                elif kind == "closing":
                    await ws.send(json.dumps({"type": "error", "text": "Live session is ending - start it again."}))

    async def guard() -> None:
        """Someone locked Vaelon, signed in or switched company: this conversation (microphone and screen going to
        Google) ends at once."""
        from . import company as _co

        while _co.epoch() == started_epoch:
            await asyncio.sleep(0.5)
        try:
            await ws.send(json.dumps({"type": "error", "text": "Vaelon was locked - Live stopped."}))
        except Exception:
            pass

    async def screen_pump() -> None:
        sent_at = 0.0
        while True:
            # a picture at once when sharing is switched on, then one every few seconds
            if state["screen"] and time.time() - sent_at >= SCREEN_EVERY:
                sent_at = time.time()
                try:
                    jpeg = await loop.run_in_executor(None, screen_jpeg)
                    await up.send(json.dumps(frame_message(jpeg)))
                except Exception:
                    pass
            elif not state["screen"]:
                sent_at = 0.0
            await asyncio.sleep(0.25)

    setup = setup_message(cfg)
    try:
        await up.send(json.dumps(setup, ensure_ascii=False))
        tasks = [asyncio.create_task(t()) for t in (from_app, from_google, screen_pump, guard)]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        for t in done:
            err = t.exception() if not t.cancelled() else None
            if err is not None and "1000" not in str(err):
                try:
                    await ws.send(json.dumps({"type": "error", "text": "Live stopped: " + str(err).replace(key, "<key>")[:160]}))
                except Exception:
                    pass
    finally:
        for jid in list(state["jobs"]):
            service.cancel(jid)
        try:
            await up.close()
        except Exception:
            pass


def start(service, token: str, port: int) -> int:
    """Start the local bridge in a background thread. Returns the port it listens on (0 = not started)."""
    if websockets is None:
        STATE["error"] = 'the "websockets" package is missing: pip install "vaelon[live]"'
        return 0
    if STATE["port"]:
        return STATE["port"]
    ready = threading.Event()

    def run() -> None:
        async def main() -> None:
            for candidate in range(port, port + 6):
                import socket

                from .security.proof import exclusive

                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    exclusive(sock)  # nobody else can bind the bridge's port while it runs
                    sock.bind(("127.0.0.1", candidate))
                    server = await websockets.serve(lambda ws: _session(ws, service, token), sock=sock,
                                                    max_size=2_000_000)
                except OSError:
                    sock.close()
                    continue
                STATE["port"] = candidate
                ready.set()
                await server.wait_closed()
                return
            STATE["error"] = "no free port for the live bridge"
            ready.set()

        try:
            asyncio.run(main())
        except Exception as e:  # never take the app down
            STATE["error"] = str(e)[:200]
            ready.set()

    threading.Thread(target=run, daemon=True, name="vaelon-live").start()
    ready.wait(5)
    return STATE["port"]


def status(cfg=None) -> dict:
    """What the app needs to offer Live: is it possible, where is the bridge, which model."""
    cfg = cfg or config.Config.load()
    return {"available": available(cfg) and bool(STATE["port"]), "port": STATE["port"],
            "key": bool(config.env("GEMINI_API_KEY")), "library": websockets is not None,
            "model": getattr(cfg, "live_model", "") or "gemini-3.1-flash-live-preview",
            "started": time.time() if STATE["port"] else 0}
