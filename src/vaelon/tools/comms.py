"""Communication tools: email, SMS and phone calls (Twilio), and contacts. Every outbound action needs human approval.

Set up in the app (Settings > Phone and email) or with `vaelon key set`; values live in the encrypted vault:
  VAELON_SMTP_USER (your address), VAELON_SMTP_PASS (app password), VAELON_IMAP_USER/PASS (fallback to SMTP ones)
  TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM (the Twilio number)
  smtp_host / smtp_port / imap_host are ordinary settings.
Contacts are personal data: kept ENCRYPTED in ~/.vaelon/contacts.enc (an older plain contacts.json is moved in once).
"""
from __future__ import annotations

import email as emaillib
import imaplib
import json
import re
import smtplib
from email.message import EmailMessage
from html import escape

import requests

from .. import config
from ..security.injection import fence
from ..security.policy import Risk
from .registry import tool

_PHONE = re.compile(r"^\+\d{7,15}$")
_EMAIL = re.compile(r"^[^@\s<>]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,24}$")


def _contacts() -> dict:
    """{name: {"phone": ..., "email": ...}} from the encrypted store (a plain contacts.json is moved in once)."""
    from ..security import vault

    enc, plain = config.HOME / "contacts.enc", config.HOME / "contacts.json"
    if enc.exists():
        try:
            data = json.loads(vault.decrypt_text(enc.read_text("utf-8").strip()))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    if plain.exists():
        try:
            data = json.loads(plain.read_text("utf-8"))
        except ValueError:
            return {}
        if isinstance(data, dict):
            _save_contacts(data)
            plain.unlink(missing_ok=True)
            return data
    return {}


def _save_contacts(data: dict) -> None:
    from ..security import vault

    config.HOME.mkdir(parents=True, exist_ok=True)
    tmp = config.HOME / "contacts.tmp"
    tmp.write_text(vault.encrypt_text(json.dumps(data, ensure_ascii=False)), "utf-8")
    vault.replace(tmp, config.HOME / "contacts.enc")


def contacts_count() -> int:
    return len(_contacts())


@tool("contact_lookup", "Find a saved contact's phone/email by name", {"name": "contact name"}, group="comms")
def contact_lookup(ctx, name):
    n = name.lower()
    hits = {k: v for k, v in _contacts().items() if n in k.lower()}
    return json.dumps(hits, ensure_ascii=False) if hits else "no such contact (save one with contact_save)"


@tool("contact_save", "Save or update a contact (name with phone and/or email) so calls, SMS and emails can use it",
      {"name": "the contact's name, e.g. Mama", "?phone": "E.164 number e.g. +15550100123", "?email": "email address"},
      risk=Risk.REVERSIBLE, summary=lambda a: f"SAVE contact {a.get('name')}: {a.get('phone', '')} {a.get('email', '')}",
      group="comms")
def contact_save(ctx, name, phone="", email=""):
    from ..security import undo

    name = re.sub(r"\s+", " ", str(name)).strip()[:60]
    phone, email = str(phone).replace(" ", "").strip(), str(email).strip()
    if not name or not (phone or email):
        raise ValueError("give a name and a phone number or an email address")
    if phone and not _PHONE.match(phone):
        raise ValueError("the number must be in international format, e.g. +15550100123")
    if email and not _EMAIL.match(email):
        raise ValueError("that is not an email address")
    data = _contacts()
    before = dict(data.get(name) or {})
    entry = {**before, **({"phone": phone} if phone else {}), **({"email": email} if email else {})}
    data[name] = entry
    _save_contacts(data)

    def back():
        d = _contacts()
        if before:
            d[name] = before
        else:
            d.pop(name, None)
        _save_contacts(d)

    undo.push(f"save contact {name}", back)
    return f"saved {name}: " + ", ".join(f"{k} {v}" for k, v in entry.items())


@tool("contact_delete", "Delete a saved contact", {"name": "contact name"}, risk=Risk.REVERSIBLE,
      summary=lambda a: f"DELETE contact {a.get('name')}", group="comms")
def contact_delete(ctx, name):
    from ..security import undo

    data = _contacts()
    if name not in data:
        return f"no contact named {name}"
    gone = data.pop(name)
    _save_contacts(data)

    def back():
        d = _contacts()
        d[name] = gone
        _save_contacts(d)

    undo.push(f"delete contact {name}", back)
    return f"deleted {name}"


def _twilio(path: str, data: dict):
    sid, tok = config.env("TWILIO_ACCOUNT_SID"), config.env("TWILIO_AUTH_TOKEN")
    if not (sid and tok and config.env("TWILIO_FROM")):
        raise RuntimeError("phone is not set up: Settings > Phone and email (Twilio account SID, token and number)")
    r = requests.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/{path}.json", data=data,
                      auth=(sid, tok), timeout=20)
    r.raise_for_status()
    return r.json()


@tool("make_call", "Place a phone call that speaks a message (text-to-speech)",
      {"to": "E.164 number e.g. +15550100123", "message": "what to say", "?language": "e.g. en-US, de-DE"},
      risk=Risk.DANGEROUS, summary=lambda a: f"CALL {a.get('to')} and say: {a.get('message')}", group="comms")
def make_call(ctx, to, message, language="en-US"):
    if not _PHONE.match(to):
        raise ValueError("number must be in E.164 format, e.g. +15550100123")
    twiml = f'<Response><Say language="{escape(language)}">{escape(message)}</Say></Response>'
    j = _twilio("Calls", {"To": to, "From": config.env("TWILIO_FROM"), "Twiml": twiml})
    return f"call started, sid={j.get('sid')}"


@tool("send_sms", "Send an SMS", {"to": "E.164 number", "message": "text"}, risk=Risk.DANGEROUS,
      summary=lambda a: f"SMS to {a.get('to')}: {a.get('message')}", group="comms")
def send_sms(ctx, to, message):
    if not _PHONE.match(to):
        raise ValueError("number must be in E.164 format")
    j = _twilio("Messages", {"To": to, "From": config.env("TWILIO_FROM"), "Body": message})
    return f"sms queued, sid={j.get('sid')}"


@tool("send_email", "Send an email", {"to": "address", "subject": "subject", "body": "plain text"},
      risk=Risk.DANGEROUS, summary=lambda a: f"EMAIL to {a.get('to')}\n  Subject: {a.get('subject')}\n  {a.get('body')}",
      group="comms")
def send_email(ctx, to, subject, body):
    user, pw = config.env("VAELON_SMTP_USER"), config.env("VAELON_SMTP_PASS")
    if not (user and pw and ctx.cfg.smtp_host):
        raise RuntimeError("email is not set up: Settings > Phone and email (address, app password, provider)")
    if any(c in to + subject for c in "\r\n"):
        raise ValueError("header injection blocked")
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = user, to, subject
    m.set_content(body)
    if int(ctx.cfg.smtp_port) == 465:  # some providers only speak encrypted SMTP on 465
        with smtplib.SMTP_SSL(ctx.cfg.smtp_host, 465, timeout=30) as s:
            s.login(user, pw)
            s.send_message(m)
    else:
        with smtplib.SMTP(ctx.cfg.smtp_host, ctx.cfg.smtp_port, timeout=30) as s:
            s.starttls()
            s.login(user, pw)
            s.send_message(m)
    return f"email sent to {to}"


@tool("read_email", "List recent unread emails (untrusted content)", {"?limit": "max messages (default 5)"},
      untrusted=True, group="comms")
def read_email(ctx, limit=5):
    user = config.env("VAELON_IMAP_USER") or config.env("VAELON_SMTP_USER")
    pw = config.env("VAELON_IMAP_PASS") or config.env("VAELON_SMTP_PASS")
    if not (user and pw and ctx.cfg.imap_host):
        raise RuntimeError("email is not set up: Settings > Phone and email (address, app password, provider)")
    out = []
    try:
        limit = max(1, min(int(limit), 20))
    except (TypeError, ValueError):
        limit = 5
    with imaplib.IMAP4_SSL(ctx.cfg.imap_host, timeout=30) as im:
        im.login(user, pw)
        im.select("INBOX", readonly=True)
        _, data = im.search(None, "UNSEEN")
        for num in data[0].split()[-int(limit):]:
            _, msg = im.fetch(num, "(RFC822)")
            m = emaillib.message_from_bytes(msg[0][1])
            part = m.get_payload(decode=True) if not m.is_multipart() else next(
                (p.get_payload(decode=True) for p in m.walk() if p.get_content_type() == "text/plain"), b"")
            out.append(f"From: {m['From']}\nSubject: {m['Subject']}\n{(part or b'').decode('utf-8', 'replace')[:1500]}")
    return fence("\n---\n".join(out) or "no unread mail", "email")[0]
