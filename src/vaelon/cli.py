"""vaelon CLI."""
from __future__ import annotations

import argparse
import json
import sys

import requests

from . import __version__, config, skills
from .config import Config
from .security import audit, undo
from .security.confirm import cli_approver


def _agent(cfg):
    from .agent import Agent

    return Agent(cfg, approver=cli_approver)


def cmd_chat(a, cfg):
    ag = _agent(cfg)
    print(f"Vaelon {__version__} - model {cfg.provider}:{cfg.model}. Type 'exit' to quit, 'undo' to reverse the last action.")
    while True:
        try:
            line = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if line in ("exit", "quit"):
            break
        if line == "undo":
            print(undo.undo())
        elif line:
            print("\nvaelon>", ag.run(line))


def cmd_run(a, cfg):
    print(_agent(cfg).run(" ".join(a.text), profile=a.agent))


def cmd_voice(a, cfg):
    from .voice import Voice

    Voice(cfg).loop(_agent(cfg))


def cmd_voice_setup(a, cfg):
    from . import tts

    tts.download_voices()
    print("voices installed in", tts.voice_dir())
    if not tts.available():
        print('also run: pip install "vaelon[voice]"')


def cmd_telegram(a, cfg):
    from .channels import telegram

    telegram.run(cfg)


def cmd_schedule(a, cfg):
    from . import scheduler

    if a.action == "add":
        j = scheduler.add(" ".join(a.text), a.every, a.daily)
        print(f"scheduled {j['id']}")
    elif a.action == "remove":
        print("removed" if scheduler.remove(a.text[0]) else "no such job")
    else:
        for j in scheduler.load():
            when = f"every {j['every_minutes']} min" if j.get("every_minutes") else f"daily {j['daily']}"
            print(f"{j['id']}  {when}  {j['prompt']}")


def cmd_daemon(a, cfg):
    import threading

    from . import scheduler, server

    srv = server.serve(cfg)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        scheduler.daemon(cfg)
    except KeyboardInterrupt:
        srv.shutdown()


def cmd_inbox(a, cfg):
    for j in scheduler.inbox():
        print(f"[{j.get('job')}] {j.get('prompt')}\n  -> {j.get('answer')}\n")


def cmd_tools(a, cfg):
    from .tools import registry

    registry.load_builtin()
    print(registry.describe())


def cmd_skills(a, cfg):
    for s in skills.load_all():
        print(f"- {s.name}: {s.description}  (triggers: {', '.join(s.triggers)})")


def cmd_memory(a, cfg):
    from .memory import Memory

    m = Memory()
    if a.action == "wipe":
        from . import conversation, profile

        m.wipe()
        profile.wipe()
        conversation.wipe()
        print("memory, profile and every conversation wiped")
    elif a.action == "search":
        for i, t in m.search(" ".join(a.text)):
            print(f"#{i}: {t}")
    else:
        for i, t in m.recent():
            print(f"#{i}: {t}")


def cmd_audit(a, cfg):
    ok, n = audit.verify()
    print(f"audit log: {n} entries, chain {'OK' if ok else 'TAMPERED'}")


def cmd_config(a, cfg):
    if a.key == "confirm":  # the owner edited config.json by hand and accepts those security settings
        raw = json.loads(Config.path().read_text("utf-8")) if Config.path().exists() else {}
        config.guard_seal(raw)
        config.ALERTS.clear()
        print("The settings in config.json are trusted now:", ", ".join(f"{k}={raw.get(k)!r}" for k in config.GUARDED if k in raw))
        return
    if a.key:
        if not hasattr(cfg, a.key) or a.value is None:
            raise SystemExit(f"usage: vaelon config KEY VALUE (known keys: {', '.join(sorted(cfg.__dict__))})")
        cur = getattr(cfg, a.key)
        try:
            setattr(cfg, a.key, json.loads(a.value) if not isinstance(cur, str) else a.value)
        except ValueError:
            raise SystemExit(f"'{a.value}' is not a valid value for {a.key} (JSON, e.g. true, 5, [\"a\"])") from None
        cfg.save()
    print(json.dumps(cfg.__dict__, indent=2, ensure_ascii=False))


def cmd_doctor(a, cfg):
    print(f"Vaelon {__version__}  home={config.HOME}")
    print(f"provider={cfg.provider} model={cfg.model} local={cfg.is_local} redact_outbound={cfg.redact_outbound}")
    if cfg.provider == "ollama":
        try:
            requests.get((cfg.base_url or "http://localhost:11434") + "/api/tags", timeout=3).raise_for_status()
            print("OK   ollama reachable")
            try:
                info = requests.post((cfg.base_url or "http://localhost:11434") + "/api/show",
                                     json={"model": cfg.model}, timeout=5).json()
                if "thinking" in info.get("capabilities", []) and "instruct" not in cfg.model:
                    print(f"WARN {cfg.model} is a 'thinking' model: slow and rambling. Better: "
                          f"ollama pull qwen3:4b-instruct  then  vaelon config model qwen3:4b-instruct")
            except Exception:
                pass
        except Exception:
            print("FAIL ollama not reachable - install from ollama.com and run: ollama pull " + cfg.model)
    import os
    import time

    from .security import dlp, integrity, vault

    leaked_env = sorted(n for n in dlp.known_names() if os.environ.get(n))
    if leaked_env:
        print("WARN these keys are in plain environment variables (every program can read them): "
              + ", ".join(leaked_env) + ". Safer: vaelon key set NAME, then remove the variable.")
    for f in sorted((config.HOME / "secrets").glob("key_*")):
        age = int((time.time() - f.stat().st_mtime) / 86400)
        print(f"{'WARN' if age >= 90 else 'OK  '} {f.name[4:]} stored encrypted, {age} days old"
              + (" - rotate it (make a new key, vaelon key set ...)" if age >= 90 else ""))
    if cfg.tts_engine == "elevenlabs":
        from . import tts

        print(f"OK   ElevenLabs used this month by Vaelon: {tts.elevenlabs_used()} / {cfg.elevenlabs_monthly_chars} chars")
    _audit_dependencies()

    print(f"{'OK  ' if vault.available() else 'WARN'} encryption at rest (AES-256-GCM){'' if vault.available() else ': pip install cryptography'}")
    ok, problems = integrity.verify_code()
    print(f"{'OK  ' if ok else 'WARN'} code integrity{'' if ok else ': ' + '; '.join(problems[:3])}")
    from . import market_data, mcp

    print("OK   stock data: " + " -> ".join(market_data.sources())
          + ("" if len(market_data.sources()) > 1 else "  (unofficial; free keys: TWELVEDATA_API_KEY, FINNHUB_API_KEY)"))
    from . import search

    print("OK   web search: " + " -> ".join(search.sources())
          + ("" if len(search.sources()) > 2 else "  (public engines can refuse; free keys: TAVILY_API_KEY, BRAVE_SEARCH_API_KEY)"))
    approved = mcp.servers()
    for n in mcp.names():
        print(f"OK   MCP server {n}: {len(approved[n].get('tools') or {})} approved tools" if n in approved
              else f"WARN MCP server {n} is ignored: its file was changed outside Vaelon (vaelon mcp refresh {n})")
    for mod in ("psutil", "faster_whisper", "sounddevice", "pyttsx3", "ddgs"):
        try:
            __import__(mod)
            print(f"OK   {mod}")
        except ImportError:
            print(f"--   {mod} (optional)")


def _audit_dependencies() -> None:
    """Known vulnerabilities in the installed libraries that guard your keys and data (OSV.dev, no key needed)."""
    from importlib import metadata

    pkgs = ("requests", "urllib3", "certifi", "cryptography", "idna", "pywebview", "piper-tts", "numpy")
    queries, names = [], []
    for name in pkgs:
        try:
            queries.append({"package": {"name": name, "ecosystem": "PyPI"}, "version": metadata.version(name)})
            names.append(name)
        except metadata.PackageNotFoundError:
            continue
    try:
        r = requests.post("https://api.osv.dev/v1/querybatch", json={"queries": queries}, timeout=15)
        r.raise_for_status()
        results = r.json().get("results", [])
    except Exception:
        print("--   dependency check skipped (offline)")
        return
    bad = [(n, q["version"], len(res.get("vulns", []))) for n, q, res in zip(names, queries, results) if res.get("vulns")]
    if not bad:
        print(f"OK   no known vulnerabilities in {len(names)} security-relevant libraries")
    for n, v, k in bad:
        print(f"WARN {n} {v}: {k} known vulnerabilities - update: pip install -U {n}")


def cmd_learn(a, cfg):
    from .tools import registry

    ag = _agent(cfg)
    ctx = registry.Ctx(cfg, ag.memory, ag.approver, ag.hooks)
    ctx.extra["agent"] = ag
    print(registry.execute(ctx, "learn", {"topic": " ".join(a.topic), "url": a.url} if a.url
                           else {"topic": " ".join(a.topic)}))


def cmd_study(a, cfg):
    """Self-study session: web + GitHub research on each study topic (schedule it nightly)."""
    from .security.confirm import deny_all
    from .tools import registry

    ag = _agent(cfg)
    ctx = registry.Ctx(cfg, ag.memory, deny_all, ag.hooks)
    ctx.extra["agent"] = ag
    for topic in (a.topics or cfg.study_topics):
        print(f"\n## {topic}")
        print(registry.execute(ctx, "learn", {"topic": topic}))
        print(registry.execute(ctx, "research_code", {"topic": topic}))


def cmd_about(a, cfg):
    from . import ABOUT, __source__

    print(ABOUT)
    print("License: see the LICENSE and NOTICE files." + (f"\nSource: {__source__}" if __source__ else ""))


def cmd_update(a, cfg):
    from . import updates

    print(updates.report())


def cmd_token(a, cfg):
    from . import server

    print(server.get_token())


def cmd_integrity(a, cfg):
    from .security import integrity

    if a.action == "sign":
        print(f"signed {integrity.sign_code()} files as the trusted baseline")
        return
    ok, problems = integrity.verify_code()
    nl = "\n  "
    print("OK - code matches the signed manifest" if ok else "CHANGED:" + nl + nl.join(problems))


def cmd_trust(a, cfg):
    from .security import integrity

    kind = "plugins" if a.kind == "plugin" else "hooks"
    f = config.HOME / kind / f"{a.name}.py"
    if not f.exists():
        raise SystemExit(f"not found: {f}")
    from .tools.evolve import validate_plugin

    problems = validate_plugin(f.read_text("utf-8"))
    print(f.read_text("utf-8")[:3000])
    if problems:
        print("\nSTATIC CHECK WARNINGS: " + "; ".join(problems))
    if input(f"\nRun this {a.kind} as code on this PC? [y/N] ").strip().lower() in ("y", "yes", "да"):
        print("trusted, sha256 " + integrity.trust(kind, f)[:16] + "...")


def cmd_app(a, cfg):
    from . import desktop

    desktop.run(cfg)


def cmd_evolution(a, cfg):
    from . import evolution

    if a.action == "rollback":
        print(evolution.rollback())
    else:
        for h in evolution.history() or [{"time": "-", "file": "no self-modifications yet", "reason": ""}]:
            print(f"{h['time']}  {h['file']}  {h['reason']}")


def cmd_key(a, cfg):
    """API keys live ENCRYPTED in the vault (DPAPI on Windows) - never in config.json or the chat."""
    import getpass
    import re

    from .providers import EXTRA_KEYS, PRESETS
    from .security import vault

    import time

    from .security import dlp

    known = sorted({p["api_key_env"] for p in PRESETS.values() if p["api_key_env"]} | set(EXTRA_KEYS))
    stray = [f for f in (config.HOME / "secrets").glob("key_*")  # misnamed entries only, never your real settings
             if dlp.looks_like_secret(f.name[4:]) or (f.name[4:] not in known
                                                      and not f.name[4:].startswith(("VAELON_", "TWILIO_")))]

    if a.action == "clean":
        # entries with an unknown name - e.g. a key pasted where the NAME goes - are removed without retyping them
        for f in stray:
            f.unlink(missing_ok=True)
        dlp.forget_cache()
        print(f"removed {len(stray)} misnamed entr{'y' if len(stray) == 1 else 'ies'}" if stray else "nothing to clean")
        return
    if a.action == "list":
        if stray:
            print(f"WARN {len(stray)} entry with an unknown name (a key pasted as the name?). Remove: vaelon key clean")
        for name in known:
            f = config.HOME / "secrets" / f"key_{name}"
            age = int((time.time() - f.stat().st_mtime) / 86400) if f.exists() else None
            have = "set" if config.env(name) else "-"
            why = EXTRA_KEYS.get(name, ("model provider", ""))[0]
            note = f"  (set {age} days ago{' - consider rotating it' if age >= 90 else ''})" if age is not None else ""
            print(f"{have:4} {name:24} {why}{note}")
        return
    raw = (a.name or "").strip()
    if a.action == "set" and not raw:  # no name typed: pick from the list (nothing secret is typed on the command line)
        for i, n in enumerate(known, 1):
            print(f"{i:2}. {n:24} {EXTRA_KEYS.get(n, ('model provider', ''))[0]}")
        choice = input("which key? number: ").strip()
        if not choice.isdigit() or not 1 <= int(choice) <= len(known):
            print("nothing saved")
            return
        raw = known[int(choice) - 1]
    if dlp.looks_like_secret(raw):
        print("STOP: that looks like the KEY itself, typed where the NAME goes. Nothing was saved.\n"
              "Use:  vaelon key set GROQ_API_KEY   (or just: vaelon key set)  and paste the key at the hidden prompt.\n"
              "The key was shown on screen - for safety, revoke it on the provider's site and make a new one.")
        return
    name = raw.upper()
    if not re.fullmatch(r"[A-Z0-9_]{2,64}", name):
        print("give a key name, e.g.  vaelon key set GROQ_API_KEY   (or just: vaelon key set)")
        return
    if a.action == "set" and name not in known and not name.startswith(("VAELON_", "TWILIO_")):
        if input(f"'{name}' is not a known key name ({', '.join(known[:4])}, ...). Save anyway? [y/N] ").lower() != "y":
            print("nothing saved")
            return
    path = config.HOME / "secrets" / f"key_{name}"
    if a.action == "delete":
        path.unlink(missing_ok=True)
        dlp.forget_cache()
        print(f"{name} deleted")
        return
    value = getpass.getpass(f"paste {name} (hidden): ").strip()
    if not value:
        print("nothing saved")
        return
    shapes = {"GROQ_API_KEY": "gsk_", "ELEVENLABS_API_KEY": "sk_", "OPENROUTER_API_KEY": "sk-or-",
              "ANTHROPIC_API_KEY": "sk-ant-"}  # Google keys come in more than one shape: no check
    if name in shapes and not value.startswith(shapes[name]):
        print(f"warning: {name} keys normally start with '{shapes[name]}' - check you pasted the right thing")
    if any(c.isspace() for c in value) or len(value) < 16:
        print("that does not look like an API key (too short or contains spaces) - nothing saved")
        return
    vault.write_secret(f"key_{name}", value.encode())
    dlp.forget_cache()
    print(f"{name} saved encrypted in the vault (only your Windows account on this PC can unseal it)")


def _yes(question: str) -> bool:
    return input(question + " [y/N] ").strip().lower() in ("y", "yes", "да")


def cmd_company(a, cfg):
    """Company mode: people with roles, separate companies, the journal. The app has the full screen for it."""
    import getpass

    from . import company, journal

    if a.action == "status":
        s = company.state()
        print("Company mode:", "ON" if s["enabled"] else "off")
        if s["enabled"]:
            print("Companies:", ", ".join(w["name"] for w in company.workspaces()))
            print("People:", ", ".join(f"{u['name']} ({u['role']})" for u in company.users()))
            for w in company.workspaces():
                d = company.config.HOME if w["id"] == company.PERSONAL else company.config.HOME / "workspaces" / w["id"]
                print(f"Journal of {w['name']}:", journal.verify(d)[1])
        return
    if a.action == "enable":
        name = input("Your name (the owner): ").strip()
        pin = getpass.getpass("Choose a PIN (4-8 digits): ")
        if pin != getpass.getpass("The PIN again: "):
            sys.exit("The two PINs differ - nothing changed.")
        company.enable(name, pin)
        print("Company mode is on. Add companies and people in the app (Money > Company) or keep using it alone.")
        return
    if a.action == "disable":
        company.disable(getpass.getpass("The owner's PIN: "))
        print("Company mode is off. People, companies and journals are kept for later.")
        return
    if a.action == "reset-owner-pin":
        # whoever can run this on the owner's Windows account could also open the data: it is said in the journal
        print("This sets a new PIN for the owner. It is written in the journal.")
        pin = getpass.getpass("New owner PIN (4-8 digits): ")
        if pin != getpass.getpass("The PIN again: "):
            sys.exit("The two PINs differ - nothing changed.")
        data = company.load(strict=True)
        owner = next((u for u in data["users"] if u["role"] == "owner"), None)
        if not owner:
            sys.exit("There is no owner yet: use 'vaelon company enable'.")
        owner.update(company._pin_fields(pin))
        company._store(data)
        data["fails"] = {}
        company._store(data)
        journal.add("owner PIN reset from the command line", owner["name"], who="command line", admin=True)
        print("Done.")


def _cli_sign_in() -> None:
    """Company mode: the command line asks who is there, like the app does."""
    import getpass

    from . import company

    if not company.enabled() or company.user():
        return
    people = company.load()["users"]
    name = input("Vaelon is in company mode. Your name: ").strip().lower()
    u = next((x for x in people if x["name"].lower() == name), None)
    try:
        who = company.sign_in(u["id"] if u else name, getpass.getpass("PIN: "))
    except company.Denied as e:
        sys.exit(str(e))
    if who["role"] != "owner":  # the command line has the owner's personal assistant behind it
        company.sign_out()
        sys.exit("In company mode the command line is for the owner only - please use the app.")


def cmd_demo(a, cfg):
    """Made-up bills, budget, deals, invoices and calendar entries to try the app; 'remove' takes only those away."""
    from . import demo

    if a.action == "load":
        out = demo.load()
        print(demo.text(out, True, False))
        print("Backup of the files before the demo:", out["backup"])
    else:
        print(demo.text(demo.remove(), False, False))


def cmd_mcp(a, cfg):
    """Connections to outside tool servers (Model Context Protocol). Only this command can add or change them."""
    from . import mcp

    name = (a.name or "").strip().lower()
    try:
        if a.action == "list":
            known = mcp.servers()
            for n in mcp.names():
                spec = known.get(n)
                if spec is None:
                    print(f"{n:12} IGNORED - its file was changed outside Vaelon. Review it:  vaelon mcp refresh {n}")
                    continue
                where = spec.get("url") or " ".join(spec.get("command") or [])
                print(f"{n:12} {'on ' if spec.get('enabled', True) else 'off'} {len(spec.get('tools') or {}):3} tools  {where}")
                for tool in sorted(spec.get("tools") or {}):
                    rid = mcp.tool_id(n, tool)
                    print(f"{'':16} {rid}  {'(runs without asking)' if rid in cfg.auto_approve else ''}")
            if not mcp.names():
                print("no MCP servers yet. Example:\n  vaelon mcp add files -- npx -y @modelcontextprotocol/server-filesystem "
                      "C:\\Users\\you\\Documents")
            return
        if a.action in ("add", "refresh"):
            spec = None
            if a.action == "refresh" or (not a.command and not a.url):
                f = mcp.folder() / f"{name}.json"  # refresh also re-approves a file that was edited outside
                spec = json.loads(f.read_text("utf-8")) if f.is_file() else None
                if spec is None:
                    raise mcp.McpError(f"no server named '{name}'" if a.action == "refresh"
                                       else "give a command after -- or an address with --url")
            else:
                spec = {"enabled": True}
                if a.url:
                    spec["url"] = a.url
                else:
                    spec["command"] = list(a.command)
                env = dict(kv.split("=", 1) for kv in a.env or [] if "=" in kv)
                if env:
                    spec["env"] = {k: v.upper() for k, v in env.items()}
                if a.key:
                    spec["key"] = a.key.upper()
                if a.words:
                    spec["words"] = [w.lower() for w in a.words]
            mcp.validate(name, spec)
            what = spec.get("url") or " ".join(spec.get("command") or [])
            print(f"MCP server '{name}':  {what}")
            if spec.get("command"):
                print("This PROGRAM will run on your PC with your user rights whenever one of its tools is used.")
            else:
                print("What Vaelon passes to its tools is SENT to that address.")
            for var, key_name in (spec.get("env") or {}).items():
                print(f"  it receives your stored key {key_name} (as {var})")
            if spec.get("key"):
                print(f"  it receives your stored key {spec['key']} (as a Bearer token)")
            if not _yes("Connect now and list its tools?"):
                print("nothing saved")
                return
            good, bad = mcp.inspect(name, spec)
            for tool, pin in good.items():
                print(f"  + {tool}: {mcp.clean(pin['description'], 110)}")
            for tool, why in bad:
                print(f"  - {tool}: NOT offered to Vaelon - {why}")
            if not good:
                print("no usable tools - nothing saved")
                return
            if not _yes(f"Let Vaelon use these {len(good)} tools (it will still ask before every call)?"):
                print("nothing saved")
                return
            spec["tools"] = good
            mcp.save(name, spec)
            print(f"saved. Vaelon sees them after a restart. Mention '{name}' in a request to bring them up.")
            return
        spec = mcp.load(name)
        if a.action == "remove":
            for rid in [mcp.tool_id(name, t) for t in (spec or {}).get("tools", {})]:
                if rid in cfg.auto_approve:
                    cfg.auto_approve.remove(rid)
            cfg.save()
            print("removed" if mcp.remove(name) else f"no server named '{name}'")
            return
        if spec is None:
            raise mcp.McpError(f"no approved server named '{name}' (vaelon mcp list)")
        if a.action in ("enable", "disable"):
            spec["enabled"] = a.action == "enable"
            mcp.save(name, spec)
            print(f"{name} {a.action}d (restart Vaelon to apply)")
        elif a.action in ("allow", "ask"):
            tool = (a.tool or "").strip()
            if tool not in spec.get("tools", {}):
                raise mcp.McpError(f"'{name}' has no tool '{tool}'. Its tools: {', '.join(sorted(spec.get('tools', {})))}")
            rid = mcp.tool_id(name, tool)
            if a.action == "allow" and rid not in cfg.auto_approve:
                print(f"'{tool}' will run WITHOUT asking you, and what Vaelon passes to it leaves Vaelon.\n"
                      "Vaelon still asks whenever the task has read outside content (a web page, an e-mail, a file).")
                if not _yes("Allow?"):
                    return
                cfg.auto_approve.append(rid)
            elif a.action == "ask" and rid in cfg.auto_approve:
                cfg.auto_approve.remove(rid)
            cfg.save()
            print(f"{rid}: {'runs without asking' if rid in cfg.auto_approve else 'asks before every call'}")
    except mcp.McpError as e:
        print(f"MCP: {e}")
    except (OSError, ValueError) as e:
        print(f"MCP: {type(e).__name__}: {e}")


def cmd_provider(a, cfg):
    from . import providers

    if not a.name:
        for n, p in providers.PRESETS.items():
            mark = "*" if (cfg.provider, cfg.base_url) == (p["provider"], p["base_url"]) else " "
            print(f"{mark} {n:11} {p['model']:42} {p['free']:34} {p['url']}")
        return
    p = providers.apply(cfg, a.name)
    if a.model:
        cfg.model = a.model
        cfg.save()
    print(f"provider: {a.name}  model: {cfg.model}")
    if p["api_key_env"] and not config.env(p["api_key_env"]):
        print(f"get a key at {p['url']}  then run:  vaelon key set {p['api_key_env']}")
    elif not a.model:
        changed = providers.pick_available(cfg, a.name)
        if changed:
            print(f"the preset model is no longer offered - switched to: {changed}  (all options: vaelon models)")
    if a.name != "local":
        print("note: your messages will be sent to this provider (secrets are redacted). `vaelon provider local` "
              "switches back to fully private.")


def cmd_models(a, cfg):
    from . import providers

    try:
        for m in providers.list_models(cfg):
            print(m)
    except Exception as e:
        print(f"could not list models: {e}")


def cmd_voice_design(a, cfg):
    from . import tts

    if a.preset:
        cfg.voice = tts.normalize({"preset": a.preset})
    v = tts.normalize(cfg.voice or tts.current_voice(cfg))
    for kv in a.set or []:
        k, _, val = kv.partition("=")
        v = tts.normalize({**v, k.strip(): val})
    if a.preset or a.set:
        cfg.voice = v
        cfg.save()
    print(json.dumps(v, ensure_ascii=False))
    print("presets: " + ", ".join(tts.PRESETS))


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # Bulgarian output on Windows consoles
        except Exception:
            pass
    p = argparse.ArgumentParser(prog="vaelon", description="Vaelon - private open-source AI agent")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("chat").set_defaults(fn=cmd_chat)
    r = sub.add_parser("run")
    r.add_argument("text", nargs="+")
    r.add_argument("--agent", choices=["coder", "researcher", "operator", "comms"])
    r.set_defaults(fn=cmd_run)
    sub.add_parser("voice").set_defaults(fn=cmd_voice)
    sub.add_parser("voice-setup").set_defaults(fn=cmd_voice_setup)
    sub.add_parser("telegram").set_defaults(fn=cmd_telegram)
    sc = sub.add_parser("schedule")
    sc.add_argument("action", choices=["add", "list", "remove"])
    sc.add_argument("text", nargs="*")
    sc.add_argument("--every", type=int, help="minutes")
    sc.add_argument("--daily", help="HH:MM")
    sc.set_defaults(fn=cmd_schedule)
    sub.add_parser("daemon").set_defaults(fn=cmd_daemon)
    sub.add_parser("inbox").set_defaults(fn=cmd_inbox)
    sub.add_parser("tools").set_defaults(fn=cmd_tools)
    sub.add_parser("skills").set_defaults(fn=cmd_skills)
    m = sub.add_parser("memory")
    m.add_argument("action", choices=["list", "search", "wipe"])
    m.add_argument("text", nargs="*")
    m.set_defaults(fn=cmd_memory)
    sub.add_parser("audit").set_defaults(fn=cmd_audit)
    c = sub.add_parser("config")
    c.add_argument("key", nargs="?")
    c.add_argument("value", nargs="?")
    c.set_defaults(fn=cmd_config)
    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
    cp = sub.add_parser("company", help="company mode: people with roles, companies, the journal")
    cp.add_argument("action", choices=["status", "enable", "disable", "reset-owner-pin"])
    cp.set_defaults(fn=cmd_company)
    dm = sub.add_parser("demo", help="load / remove made-up data to try the Money panel and the calendar")
    dm.add_argument("action", choices=["load", "remove"])
    dm.set_defaults(fn=cmd_demo)
    lr = sub.add_parser("learn", help="research a topic on the web and remember the key facts")
    lr.add_argument("topic", nargs="+")
    lr.add_argument("--url", default="")
    lr.set_defaults(fn=cmd_learn)
    st = sub.add_parser("study", help="self-study: research the web and GitHub on your study topics")
    st.add_argument("topics", nargs="*")
    st.set_defaults(fn=cmd_study)
    sub.add_parser("app", help="open Vaelon as a desktop app").set_defaults(fn=cmd_app)
    sub.add_parser("token", help="print the local API access key").set_defaults(fn=cmd_token)
    sub.add_parser("about", help="author, license and version").set_defaults(fn=cmd_about)
    sub.add_parser("update", help="check whether a newer release exists").set_defaults(fn=cmd_update)
    ig = sub.add_parser("integrity", help="verify or re-sign Vaelon's code fingerprints")
    ig.add_argument("action", choices=["verify", "sign"])
    ig.set_defaults(fn=cmd_integrity)
    tr = sub.add_parser("trust", help="approve a plugin or hook you wrote yourself")
    tr.add_argument("kind", choices=["plugin", "hook"])
    tr.add_argument("name")
    tr.set_defaults(fn=cmd_trust)
    ev = sub.add_parser("evolution", help="history / rollback of Vaelon's changes to its own code")
    ev.add_argument("action", choices=["history", "rollback"])
    ev.set_defaults(fn=cmd_evolution)
    k = sub.add_parser("key", help="store an API key encrypted in the vault (list / set NAME / delete NAME)")
    k.add_argument("action", choices=["list", "set", "delete", "clean"])
    k.add_argument("name", nargs="?")
    k.set_defaults(fn=cmd_key)
    pv = sub.add_parser("provider", help="switch the AI model provider: local, groq, gemini, openrouter, ...")
    pv.add_argument("name", nargs="?", choices=["local", "groq", "gemini", "openrouter", "cerebras", "mistral",
                                                 "openai", "anthropic"])
    pv.add_argument("--model", default="")
    pv.set_defaults(fn=cmd_provider)
    sub.add_parser("models", help="list the models the current provider offers you").set_defaults(fn=cmd_models)
    mc = sub.add_parser("mcp", help="outside tool servers (MCP):  mcp add files -- npx -y <server> <args>")
    mc.add_argument("action", choices=["list", "add", "refresh", "remove", "enable", "disable", "allow", "ask"])
    mc.add_argument("name", nargs="?", help="your short name for the server, e.g. files")
    mc.add_argument("tool", nargs="?", help="allow / ask: the tool's name")
    mc.add_argument("--url", default="", help="address of a remote server (https)")
    mc.add_argument("--env", action="append", metavar="VAR=KEY_NAME",
                    help="give the program a key stored with `vaelon key set KEY_NAME` as environment variable VAR")
    mc.add_argument("--key", default="", metavar="KEY_NAME", help="stored key sent to --url as a Bearer token")
    mc.add_argument("--words", nargs="*", help="extra words that bring these tools up, e.g. --words repo issue")
    mc.set_defaults(fn=cmd_mcp, command=[])
    vd = sub.add_parser("voice-design", help="shape Vaelon's voice: --preset titan  --set pitch=0.85 echo=0.3")
    vd.add_argument("--preset")
    vd.add_argument("--set", nargs="*")
    vd.set_defaults(fn=cmd_voice_design)
    argv = list(sys.argv[1:] if argv is None else argv)
    tail = []
    if argv[:1] == ["mcp"] and "--" in argv:  # everything after -- is the server's own command line
        cut = argv.index("--")
        argv, tail = argv[:cut], argv[cut + 1:]
    a = p.parse_args(argv)
    if tail:
        a.command = tail
    if not a.cmd:
        a.fn = cmd_chat
    if a.fn in (cmd_chat, cmd_run, cmd_demo) or a.cmd in ("voice", "telegram", "daemon", "learn", "study", "schedule",
                                                           "memory", "app"):
        _cli_sign_in()  # company mode: everything that runs the owner's assistant asks who is there
    a.fn(a, Config.load())


if __name__ == "__main__":
    sys.exit(main())
