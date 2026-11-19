"""Control Vaelon from your phone via Telegram (long polling, no inbound ports).

Set VAELON_TELEGRAM_TOKEN (from @BotFather) and add your chat id to `telegram_allowed_chats`.
Unknown chats are refused (and told their id so YOU can allow them). Dangerous actions are
confirmed by replying  yes  /  no  in the chat - the model cannot answer for you.
"""
from __future__ import annotations

import time

import requests

from ..agent import Agent
from ..config import Config, env
from ..security import audit
from ..security.confirm import ConfirmRequest


def run(cfg: Config | None = None) -> None:
    cfg = cfg or Config.load()
    token = env("VAELON_TELEGRAM_TOKEN")
    if not token:
        raise SystemExit("set VAELON_TELEGRAM_TOKEN")
    api = f"https://api.telegram.org/bot{token}"
    allowed = {str(c) for c in cfg.telegram_allowed_chats}

    def _sender_ok(m: dict) -> bool:
        """Private chat: the sender IS the chat. A group: only a sender whose own id is allowed too."""
        sender = str((m.get("from") or {}).get("id", ""))
        chat_id = str(m.get("chat", {}).get("id", ""))
        return bool(sender) and (sender == chat_id or sender in allowed)
    state = {"chat": None, "offset": 0}

    def send(chat, text):
        for i in range(0, len(text) or 1, 3900):
            requests.post(f"{api}/sendMessage", json={"chat_id": chat, "text": text[i:i + 3900]}, timeout=20)

    def poll_reply(chat, timeout=120):
        end = time.time() + timeout
        while time.time() < end:
            r = requests.get(f"{api}/getUpdates", params={"offset": state["offset"], "timeout": 10}, timeout=30).json()
            for u in r.get("result", []):
                state["offset"] = u["update_id"] + 1
                m = u.get("message", {})
                # the answer must come from the allowed person in the allowed chat (in a group, anyone could type "yes")
                if str(m.get("chat", {}).get("id")) == str(chat) and _sender_ok(m):
                    return m.get("text", "")
        return ""

    def approver(req: ConfirmRequest) -> bool:
        chat = state["chat"]
        from ..security.confirm import shown

        body = "\n".join("| " + line for line in shown(req.summary).splitlines())
        note = f"\n-- Vaelon: {req.note}" if req.note else ""
        send(chat, f"CONFIRM {req.tool}\n{body}{note}\nReply 'yes' to allow (anything else denies).")
        return poll_reply(chat).strip().lower() in ("yes", "y", "да")

    agent = Agent(cfg, approver=approver)
    print("Telegram channel running. Ctrl+C to stop.")
    while True:
        try:
            r = requests.get(f"{api}/getUpdates", params={"offset": state["offset"], "timeout": 25}, timeout=40).json()
        except requests.RequestException:
            time.sleep(3)
            continue
        for u in r.get("result", []):
            state["offset"] = u["update_id"] + 1
            m = u.get("message") or {}
            chat, text = str(m.get("chat", {}).get("id", "")), m.get("text", "")
            if not text:
                continue
            if chat not in allowed or not _sender_ok(m):
                audit.log("telegram_denied", chat=chat)
                send(chat, f"Not authorised. Your chat id is {chat}. Add it to telegram_allowed_chats to allow.")
                continue
            state["chat"] = chat
            try:
                send(chat, agent.run(text))
            except Exception as e:  # one failed request must not end the channel (nor print the bot's URL)
                audit.log("telegram_error", error=type(e).__name__)
                try:
                    send(chat, "Something went wrong with that request - try again.")
                except Exception:
                    pass
