"""What the app's Settings screen and the first-run setup may read and change - and nothing more.

The app talks to the core on 127.0.0.1 with the access key, so only the owner's own window reaches this. Still:
- Only the fields in `apply` can be changed. Never from here: allowed folders, tools that skip approval, a custom
  server address, MCP servers (those stay terminal-only, where the owner sees exactly what will run).
- API keys go ONE way: app -> core -> encrypted vault. No endpoint ever returns a key, a part of it or its length;
  the name of a key is all that is logged. Keys are accepted only for names Vaelon knows.
- A cloud provider can be chosen only after its key is stored, and the answer says that text will leave the PC.
"""
from __future__ import annotations

import re
import time

import requests

from . import __feedback__, __version__, config, providers
from .security import audit

SHAPES = {"GROQ_API_KEY": "gsk_", "ELEVENLABS_API_KEY": "sk_", "OPENROUTER_API_KEY": "sk-or-",
          "ANTHROPIC_API_KEY": "sk-ant-"}  # Google keys come in more than one shape: no check
MODEL_RX = re.compile(r"[A-Za-z0-9._:/@\-]{1,100}")
HOST_RX = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+")
# not secrets, but personal: kept in the vault too, shown only as "set"
IDS = {"VAELON_SMTP_USER": ("your email address (Vaelon sends and reads mail as you)", ""),
       "TWILIO_FROM": ("your Twilio phone number (calls and SMS come from it)", "https://console.twilio.com")}
COMM_KEYS = ("VAELON_SMTP_USER", "VAELON_SMTP_PASS", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM")
MAIL = {"gmail": ("smtp.gmail.com", 587, "imap.gmail.com"), "outlook": ("smtp.office365.com", 587, "outlook.office365.com"),
        "icloud": ("smtp.mail.me.com", 587, "imap.mail.me.com"), "yahoo": ("smtp.mail.yahoo.com", 587, "imap.mail.yahoo.com")}
TTS = ("auto", "piper", "sapi", "elevenlabs")
STT = ("auto", "local", "groq")


def known_keys() -> dict[str, dict]:
    """Every key name the app accepts: {NAME: {what, url, provider}} (provider = the model preset it unlocks)."""
    out = {}
    for preset, p in providers.PRESETS.items():
        if p["api_key_env"]:
            out[p["api_key_env"]] = {"what": f"{preset} - {p['free']}", "url": p["url"], "provider": preset}
    for name, (what, url) in providers.EXTRA_KEYS.items():
        out[name] = {"what": what, "url": url, "provider": None}
    for name, (what, url) in IDS.items():
        out[name] = {"what": what, "url": url, "provider": None}
    return out


def key_problem(name: str, value: str) -> str | None:
    """Why this must not be stored (None = fine). The text never repeats the value."""
    if name not in known_keys():
        return "unknown key name"
    if not isinstance(value, str) or not value.strip():
        return "the key is empty"
    value = value.strip()
    if name == "VAELON_SMTP_USER":
        return None if re.fullmatch(r"[^@\s<>]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,24}", value) else "that is not an email address"
    if name == "TWILIO_FROM":
        return None if re.fullmatch(r"\+\d{7,15}", value.replace(" ", "")) else "the number must be in international form, e.g. +15550100123"
    if any(c.isspace() for c in value) or not 16 <= len(value) <= 512 or not value.isprintable():
        return "that does not look like an API key (16-512 characters, no spaces)"
    if name in SHAPES and not value.startswith(SHAPES[name]):
        return f"{name} keys start with '{SHAPES[name]}' - check that you pasted the right key"
    return None


def set_key(name: str, value: str) -> str | None:
    """Seal a key in the vault. Returns the problem, or None when it is stored."""
    from .security import dlp, vault

    problem = key_problem(name, value)
    if problem:
        return problem
    value = value.strip().replace(" ", "") if name == "TWILIO_FROM" else value.strip()
    vault.write_secret(f"key_{name}", value.encode())
    dlp.forget_cache()
    audit.log("key_set", name=name, via="app")
    return None


def delete_key(name: str) -> bool:
    from .security import dlp

    if name not in known_keys():
        return False
    f = config.HOME / "secrets" / f"key_{name}"
    had = f.exists()
    f.unlink(missing_ok=True)
    dlp.forget_cache()
    if had:
        audit.log("key_deleted", name=name, via="app")
    return had


def keys() -> list[dict]:
    """State of every known key - never the key itself."""
    rows = []
    for name, info in known_keys().items():
        f = config.HOME / "secrets" / f"key_{name}"
        stored = f.exists()
        rows.append({"name": name, **info, "set": bool(config.env(name)), "stored": stored,
                     "age_days": int((time.time() - f.stat().st_mtime) / 86400) if stored else None})
    return rows


def preset_of(cfg) -> str | None:
    for name, p in providers.PRESETS.items():
        if (cfg.provider, cfg.base_url or "") == (p["provider"], p["base_url"]):
            return name
    return None


def comms(cfg) -> dict:
    """Phone and email: what is set up (never the values)."""
    from .tools import comms as tools_comms

    have = {k: bool(config.env(k)) for k in COMM_KEYS}
    provider = next((p for p, (smtp, port, imap) in MAIL.items()
                     if (cfg.smtp_host, cfg.smtp_port, cfg.imap_host) == (smtp, port, imap)), "custom" if cfg.smtp_host else "")
    try:
        contacts = tools_comms.contacts_count()
    except Exception:
        contacts = 0
    return {"provider": provider, "smtp_host": cfg.smtp_host, "smtp_port": cfg.smtp_port, "imap_host": cfg.imap_host,
            "email_ready": have["VAELON_SMTP_USER"] and have["VAELON_SMTP_PASS"] and bool(cfg.smtp_host),
            "phone_ready": have["TWILIO_ACCOUNT_SID"] and have["TWILIO_AUTH_TOKEN"] and have["TWILIO_FROM"],
            "contacts": contacts, "providers": list(MAIL)}


def ollama(cfg) -> dict:
    """Is the local model server there, and which models does it hold? (a quick look, 1.5 s at most)"""
    base = cfg.base_url if cfg.provider == "ollama" and cfg.base_url else "http://localhost:11434"
    try:
        r = requests.get(base + "/api/tags", timeout=1.5)
        r.raise_for_status()
        return {"reachable": True, "models": sorted(m["name"] for m in r.json().get("models", []))[:50]}
    except (requests.RequestException, ValueError, KeyError):
        return {"reachable": False, "models": []}


def warnings() -> list[str]:
    """Problems the owner must see in the app (not only in a terminal): code or security settings changed outside."""
    out = []
    try:
        from .server import INTEGRITY

        if not INTEGRITY.get("ok", True):
            out.append("Vaelon's code was changed outside approved updates: " + "; ".join(INTEGRITY.get("problems", [])[:3])
                       + ". If you did not change it, reinstall Vaelon (from a source install, check with: vaelon integrity verify)")
    except Exception:
        pass
    if config.ALERTS:
        out.append("These security settings were changed in config.json by something other than Vaelon, so the last "
                   "trusted values are used: " + ", ".join(config.ALERTS) + ". Nothing else to do - if YOU changed them on purpose, "
                   "confirm them from a source install with: vaelon config confirm")
    return out


def snapshot(cfg, probe: bool = False) -> dict:
    from pathlib import Path

    from . import focus, market_data, mcp, search

    have = {k["name"]: k["set"] for k in keys()}
    approved = mcp.servers()
    out = {
        "version": __version__, "first_run": not cfg.setup_done, "address_as": cfg.address_as,
        "preset": preset_of(cfg), "model": cfg.model, "local": cfg.is_local,
        "presets": [{"name": n, "model": p["model"], "note": p["free"], "url": p["url"], "key": p["api_key_env"],
                     "key_set": have.get(p["api_key_env"], True), "cloud": n != "local"}
                    for n, p in providers.PRESETS.items()],
        "keys": keys(), "tts_engine": cfg.tts_engine, "stt_engine": cfg.stt_engine, "auto_learn": cfg.auto_learn,
        "elevenlabs_monthly_chars": cfg.elevenlabs_monthly_chars,
        "output_dir": cfg.output_dir or str(Path.home() / "Documents" / "Vaelon"),
        "stock_sources": market_data.sources(), "search_sources": search.sources(),
        "comms": comms(cfg),
        "profiles": focus.listing(cfg), "feedback_mail": bool(__feedback__), "warnings": warnings(),
        "mcp": [{"name": n, "enabled": bool(approved[n].get("enabled", True)) if n in approved else False,
                 "tools": len(approved[n].get("tools") or {}) if n in approved else 0, "trusted": n in approved}
                for n in mcp.names()],
    }
    if probe:
        out["ollama"] = ollama(cfg)
    return out


def apply(cfg, changes: dict) -> tuple[list[str], str | None]:
    """Change the allowed settings on the LIVE config object (the running agent sees them at once) and save.
    Returns (changed fields, problem). On a problem nothing is changed."""
    if not isinstance(changes, dict):
        return [], "settings must be an object"
    have = {k["name"]: k["set"] for k in keys()}
    todo = []
    for field, value in changes.items():
        if field == "address_as":
            name = re.sub(r"[\x00-\x1f\x7f<>{}]", "", str(value)).strip()
            if not 1 <= len(name) <= 40:
                return [], "the name must be 1-40 characters"
            todo.append((field, name))
        elif field == "provider":
            p = providers.PRESETS.get(str(value))
            if p is None:
                return [], "unknown provider"
            if p["api_key_env"] and not have.get(p["api_key_env"]):
                return [], f"store the key {p['api_key_env']} first"
            todo.append((field, str(value)))
        elif field == "model":
            if not isinstance(value, str) or not MODEL_RX.fullmatch(value):
                return [], "that is not a model name"
            todo.append((field, value))
        elif field == "tts_engine":
            if value not in TTS:
                return [], "unknown voice engine"
            if value == "elevenlabs" and not have.get("ELEVENLABS_API_KEY"):
                return [], "store the key ELEVENLABS_API_KEY first"
            todo.append((field, value))
        elif field == "stt_engine":
            if value not in STT:
                return [], "unknown speech-to-text engine"
            todo.append((field, value))
        elif field == "auto_learn":
            if not isinstance(value, bool):
                return [], "auto_learn is on or off"
            todo.append((field, value))
        elif field == "elevenlabs_monthly_chars":
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1_000_000:
                return [], "the monthly limit is a number from 0 to 1000000"
            todo.append((field, value))
        elif field == "mail_provider":
            if value not in MAIL:
                return [], "unknown email provider"
            smtp, port, imap = MAIL[value]
            todo += [("smtp_host", smtp), ("smtp_port", port), ("imap_host", imap)]
        elif field in ("smtp_host", "imap_host"):
            if not isinstance(value, str) or (value and not HOST_RX.fullmatch(value)):
                return [], "that is not a server name"
            todo.append((field, value))
        elif field == "smtp_port":
            if isinstance(value, bool) or not isinstance(value, int) or value not in (25, 465, 587, 2525):
                return [], "the mail port is 587 (most) or 465"
            todo.append((field, value))
        elif field == "profiles":
            from . import focus

            try:
                todo.append((field, focus.clean(value)))
            except ValueError as e:
                return [], str(e)
        elif field == "setup_done":
            if value is not True:
                return [], "setup can only be marked as finished"
            todo.append((field, True))
        else:
            return [], f"'{str(field)[:40]}' cannot be changed from the app"
    todo.sort(key=lambda fv: fv[0] != "provider")  # a provider brings its own model: an explicit model wins after it
    for field, value in todo:
        if field == "provider":
            p = providers.PRESETS[value]
            for k in ("provider", "base_url", "model", "api_key_env"):
                setattr(cfg, k, p[k])
        else:
            setattr(cfg, field, value)
    cfg.save()
    if any(f == "provider" for f, _ in todo) and not any(f == "model" for f, _ in todo) and not cfg.is_local:
        try:
            providers.pick_available(cfg, preset_of(cfg) or "")  # the preset model may have been retired
        except Exception:
            pass
    changed = [f for f, _ in todo]
    if changed:
        audit.log("settings", fields=changed, via="app")
    return changed, None


def models(cfg) -> tuple[list[str], str | None]:
    """The models the current provider offers this key."""
    try:
        return [m for m in providers.list_models(cfg) if m][:300], None
    except Exception as e:
        return [], f"could not list models ({type(e).__name__})"
