"""Tool registry + guarded dispatcher (risk levels, human confirmation, taint, hooks, audit)."""
from __future__ import annotations

import json
import re

import importlib.util
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..security import audit, integrity
from ..security.confirm import ConfirmRequest
from ..security.policy import PolicyError, Risk
from ..security.redact import redact


@dataclass
class Tool:
    name: str
    description: str
    params: dict  # arg name -> short description (prefix '?' in name = optional)
    risk: Risk
    func: Callable[..., str]
    untrusted: bool = False  # output comes from the outside world (web, email, files)
    summary: Callable[[dict], str] | None = None
    group: str = "general"
    escalate: Callable[[dict], bool] | None = None  # True = THIS call needs approval (e.g. a write to a startup folder)
    egress: tuple = ()  # arguments whose TEXT goes to an outside service (a search query, a topic ...)
    private: bool = False  # the result is the user's own data (a file, mail, memory, money ...)


REGISTRY: dict[str, Tool] = {}
_describe_cache: dict = {}
# Read-only lookups whose answer stays valid for a while (seconds). A repeated question, or two parallel tasks
# needing the same page, get the stored result instead of another network round trip.
CACHE_TTL = {"web_search": 300, "web_fetch": 300, "wiki": 3600, "weather": 600, "exchange_rate": 600,
             "crypto_price": 60, "stock_quote": 60, "country_info": 86400, "economy_indicator": 86400,
             "science_papers": 1800, "book_search": 3600, "tech_news": 300, "cve_lookup": 3600,
             "package_vulns": 1800}
CACHE_MAX = 128


def tool(name, description, params=None, risk=Risk.SAFE, untrusted=False, summary=None, group="general", escalate=None,
         egress=(), private=False):
    def deco(fn):
        REGISTRY[name] = Tool(name, description, params or {}, risk, fn, untrusted, summary, group, escalate,
                              tuple(egress), private)
        return fn

    return deco


# which arguments of the built-in lookups leave the PC, and which tools return the user's own data (set here in one
# place, so a new tool cannot silently forget it)
EGRESS_ARGS = {"web_search": ("query",), "wiki": ("topic",), "learn": ("topic",), "research_code": ("topic",),
               "science_papers": ("query",), "book_search": ("query",), "tech_news": ("query",),
               "weather": ("place",), "stock_quote": ("symbol",), "crypto_price": ("coins",), "country_info": ("country",),
               "economy_indicator": ("country", "indicator"), "cve_lookup": ("cve",),
               "package_vulns": ("name",), "free_games": ("platform",), "exchange_rate": ("base", "to")}
PRIVATE_TOOLS = {"fs_read", "fs_list", "fs_search", "read_document", "look_at_image", "see_screen", "read_email",
                 "contact_lookup", "recall", "bills_list", "bills_summary", "budget_report", "budget_entries", "deals_list",
                 "agenda", "event_find", "invoices_list", "business_profile", "reminders_list", "scheduled_list",
                 "ask_folder", "folders_list", "cashflow_forecast", "quotes_list",
                 "recurring_list", "payment_reminders", "payment_reminder_draft"}


def _norm(text: str) -> str:
    import unicodedata

    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", str(text)).casefold())


SHINGLE = 16
# short secrets a 16-character piece would miss: a word with letters AND digits (6-64 characters), or any word of 4+
# characters right after password / passcode / pin / code / key / token
TOKEN_RX = re.compile(r"(?<!\w)(?=\w*\d)(?=\w*[^\W\d_])\w{6,64}(?!\w)")
# "password: x7Gq2", "pin = 4821", "code 4821" - a separator, or a value with a digit; never "keyboard", "Key West"
AFTER_KEY_RX = re.compile(r"(?i)\b(?:password|passcode|passwd|pin|code|key|token|парола|код|пин)\b"
                          r"(?:\s*[:=]\s*(\S{4,64})|\s+(?=\S*\d)(\S{4,64}))")


def _tokens(text: str) -> set[str]:
    t = unicodedata_casefold(text)[:200_000]
    found = set(TOKEN_RX.findall(t))
    found |= {(a or b).strip(".,;:!?\"'()[]") for a, b in AFTER_KEY_RX.findall(t)}
    return {w for w in found if len(w) >= 4}


def note_private(ctx, text: str, words: bool = False) -> None:
    """Remember the user's own data that entered this task (file contents, memory, profile ...). `words`: short values
    (a name, a city) matched as whole words instead of 16-character pieces."""
    store = ctx.extra.setdefault("private", {"shingles": set(), "words": set(), "tokens": set()})
    if words:
        for w in re.findall(r"\w{3,}", unicodedata_casefold(text)):
            store["words"].add(w)
        return
    n = _norm(text)[:200_000]
    for i in range(0, max(0, len(n) - SHINGLE + 1), 4):
        store["shingles"].add(n[i:i + SHINGLE])
    store.setdefault("tokens", set()).update(_tokens(text))


def note_public(ctx, text: str) -> None:
    """Tokens that also appeared in a PUBLIC result of this task (a web page, a search hit): those are not secrets."""
    ctx.extra.setdefault("public_tokens", set()).update(_tokens(text))


def unicodedata_casefold(text: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFKC", str(text)).casefold()


def _leaks_private(ctx, name: str, args: dict) -> str:
    """'' or what kind of private text an outgoing argument carries (only checked after outside content came in)."""
    t = REGISTRY.get(name)
    keys = (t.egress if t and t.egress else EGRESS_ARGS.get(name, ()))
    text = " ".join(str(args.get(k) or "") for k in keys)
    if not text.strip():
        return ""
    if len(text) > 200:
        return "task (a long text)"
    store = ctx.extra.get("private") or {}
    asked = ctx.extra.get("request_norm", "")
    n = _norm(text)
    for i in range(0, max(0, len(n) - SHINGLE + 1)):
        piece = n[i:i + SHINGLE]
        if piece in store.get("shingles", ()) and piece not in asked:
            return "files, mail or memory"
    req_words = set(re.findall(r"\w{3,}", unicodedata_casefold(ctx.extra.get("request", ""))))
    said = set(re.findall(r"\w{3,}", unicodedata_casefold(text)))
    if (said & store.get("words", set())) - req_words:
        return "profile"
    strip = ".,;:!?\"'()[]"
    said_tokens = {w.strip(strip) for w in re.findall(r"\S{4,64}", unicodedata_casefold(text))} | _tokens(text)
    request = ctx.extra.get("request", "")
    req_tokens = {w.strip(strip) for w in re.findall(r"\S{4,64}", unicodedata_casefold(request))} | _tokens(request)
    if (said_tokens & store.get("tokens", set())) - req_words - req_tokens - ctx.extra.get("public_tokens", set()):
        return "files, mail or memory"
    return ""


# After outside content entered a task (a web page, an e-mail, a file), injected text may steer the model:
# - these change what Vaelon remembers or take back the user's own actions: approval first;
TAINT_ASK = {"remember", "forget", "undo", "learn_skill", "forget_skill", "delegate",
             # money that cannot be taken back or that changes who gets paid: issued invoices (the unbroken series),
             # recurring plans that issue them by themselves, the bank details printed on them
             "business_profile", "invoice_create", "deal_won", "deal_invoice", "recurring_add", "recurring_change"}
# never covered by cfg.auto_approve (a changed config.json must not let them run unseen, not even in a scheduled task)
NEVER_AUTO = {"run_command", "self_modify", "self_rollback", "extension_enable", "create_tool", "fs_delete_permanent",
              "send_email", "send_sms", "make_call", "kill_process", "open_app", "download_file", "folder_add",
              "payment_reminder_send", "recurring_add"}
# - these send a URL out: one the model made up (e.g. "https://evil/?d=<your file>") needs approval; a URL the user
#   wrote or that came in a result of this task (a search hit, a link on a page) does not.
EGRESS = {"web_fetch": "url", "learn": "url", "download_file": "url", "check_url": "url"}
URL_RX = re.compile(r"https?://[^\s<>\"'`)\]]+")
# after the user's own data was read AND outside content may be steering the task: this many outside calls run freely,
# every further one asks (the ORDER of calls to planted links can spell out a secret - issue #30, red team R1)
EGRESS_FREE = 2


def note_urls(ctx, text: str, private: bool = False) -> None:
    """Remember the addresses that appeared in the user's request or in a result of this task. Addresses that appeared
    only in the user's OWN data (a file, a mail, a folder) are kept apart: a planted document must not be able to hand
    the model "given" addresses to leak through."""
    seen = ctx.extra.setdefault("private_urls" if private else "seen_urls", set())
    for u in URL_RX.findall(str(text))[:400]:
        seen.add(u.rstrip(".,;:!?"))


def marked_shown(ctx, records) -> None:
    """Records written after outside content carry src="chat-outside" (deals, quotes, plans, contacts, invoices made
    from them). Showing them to the model again is outside content: the task is tainted. Unlike outside_shown, a
    record's own PDF path ("file") does not count."""
    if any(isinstance(r, dict) and r.get("src") for r in records):
        ctx.tainted = True


# reads of money tools that need no card even after outside content (they change nothing)
_READS = {"business_profile": lambda a: not any(str(v).strip() for v in a.values()),
          "bank_import": lambda a: str(a.get("preview", "")).strip().lower() in ("yes", "y", "true", "да", "1")}


def outside_shown(ctx, records) -> None:
    """Records that came from an imported file (.ics, a bill read from a file, a bank statement line) carry that
    file's words. Showing them to the model is outside content, even in a later conversation: the task is tainted."""
    if any(isinstance(r, dict) and (r.get("src") or r.get("file") or r.get("ref")) for r in records):
        ctx.tainted = True


def _url_origin(ctx, name: str, args: dict) -> str:
    """"" when the address was given (the user's request, a public result of this task); "private" when it appeared only
    in the user's own data; "made_up" when it appeared nowhere."""
    key = EGRESS.get(name)
    url = str(args.get(key) or "").strip().rstrip(".,;:!?") if key else ""
    if not url or url in ctx.extra.get("seen_urls", set()):
        return ""
    return "private" if url in ctx.extra.get("private_urls", set()) else "made_up"


def _made_up_url(ctx, name: str, args: dict) -> bool:
    return bool(_url_origin(ctx, name, args))


def _is_egress(name: str) -> bool:
    t = REGISTRY.get(name)
    return name in EGRESS or bool(t and t.egress) or bool(EGRESS_ARGS.get(name))


def _in_request(ctx, name: str, args: dict) -> bool:
    """The outgoing address or text is the user's own words: never counted against the budget."""
    request = unicodedata_casefold(ctx.extra.get("request", ""))
    key = EGRESS.get(name)
    if key:
        url = str(args.get(key) or "").strip().rstrip(".,;:!?")
        return bool(url) and unicodedata_casefold(url) in request
    t = REGISTRY.get(name)
    keys = (t.egress if t and t.egress else EGRESS_ARGS.get(name, ()))
    words = set(re.findall(r"\w+", unicodedata_casefold(" ".join(str(args.get(k) or "") for k in keys))))
    return bool(words) and words <= set(re.findall(r"\w+", request))


@dataclass
class Ctx:
    """Runtime context handed to every tool."""

    cfg: Any
    memory: Any = None
    approver: Callable[[ConfirmRequest], bool] = lambda _r: False
    hooks: Any = None
    tainted: bool = False  # set when untrusted content entered this turn
    allowed_tools: set | None = None  # sub-agent capability restriction
    extra: dict = field(default_factory=dict)


def describe(allowed: set | None = None) -> str:
    key = (len(REGISTRY), frozenset(allowed) if allowed is not None else None)
    if key in _describe_cache:
        return _describe_cache[key]
    lines = []
    for t in sorted(REGISTRY.values(), key=lambda x: x.name):
        if allowed is not None and t.name not in allowed:
            continue
        args = ", ".join(f"{k}: {v}" for k, v in t.params.items())
        lines.append(f"- {t.name}({args}) [{t.risk.name}] - {t.description}")
    return "\n".join(lines)


def openai_tools(names) -> list[dict]:
    """Native function-calling specs for the given tools (cloud models)."""
    out = []
    for n in names:
        t = REGISTRY.get(n)
        if t is None:
            continue
        props = {k.lstrip("?"): {"type": "string", "description": str(v)} for k, v in t.params.items()}
        out.append({"type": "function", "function": {
            "name": t.name, "description": t.description[:500],
            "parameters": {"type": "object", "properties": props,
                           "required": [k for k in t.params if not k.startswith("?")]}}})
    return out


def execute(ctx: Ctx, name: str, args: dict) -> str:
    t = REGISTRY.get(name)
    if t is None:
        return f"ERROR: unknown tool '{name}'"
    if ctx.allowed_tools is not None and name not in ctx.allowed_tools:
        return f"ERROR: tool '{name}' is not permitted for this agent"
    if not isinstance(args, dict):
        return "ERROR: args must be an object"
    norm: dict = {}
    for k, v in args.items():  # the tool lists optional args as "?name": both spellings mean the same argument
        key = str(k).lstrip("?")
        if key in norm:
            return f"ERROR: the argument '{key}' was given twice"
        norm[key] = v
    args = norm  # from here on, the card, every check and the call itself see the very same values
    required = [k for k in t.params if not k.startswith("?")]
    missing = [k for k in required if k not in args]
    if missing:
        return f"ERROR: missing args {missing}"
    from ..security import dlp

    leaked = dlp.find(json.dumps(args, ensure_ascii=False, default=str))
    if leaked:
        audit.log("dlp_block", tool=name, secret=leaked)
        return f"BLOCKED: the arguments contain your stored secret {leaked}. Secrets never leave Vaelon."
    if ctx.hooks:
        veto = ctx.hooks.fire("pre_tool", tool=name, args=args)
        if veto:
            audit.log("hook_veto", tool=name, reason=veto)
            return f"BLOCKED by hook: {veto}"
    ttl = CACHE_TTL.get(name, 0) if t.risk == Risk.SAFE else 0
    cache = ctx.extra.get("cache") if ttl else None
    ckey = (name, json.dumps(args, sort_keys=True, ensure_ascii=False, default=str), ctx.extra.get("lang"))
    if cache is not None:
        hit = cache.get(ckey)
        if hit and time.time() - hit[0] < ttl:
            if t.untrusted:
                ctx.tainted = True  # cached outside content is still outside content
            audit.log("tool", tool=name, args=args, ok=True, cached=True)
            return hit[1]
    if t.group == "mcp":  # an outside tool server (e.g. accounting software): owner / accountant in company mode
        from .. import company

        if not company.can("integrations"):
            return "DENIED: your role may not use connected tools (MCP) in this company."
    needs_confirm = t.risk == Risk.DANGEROUS or (ctx.tainted and t.risk >= Risk.REVERSIBLE)
    # "echo": an earlier answer in the window was written after outside content; "private_read": this task already
    # read the user's own data. Then an address nobody gave, or the user's data going out, needs the user's yes too.
    echo = bool(ctx.extra.get("echo"))
    watch = ctx.tainted or echo or bool(ctx.extra.get("private_read"))
    origin = _url_origin(ctx, name, args) if watch else ""
    made_up = bool(origin)
    # the budget is for ADDRESSES only (their order can spell a secret); searches go to fixed services
    over_budget = (bool(ctx.extra.get("private_read")) and (ctx.tainted or echo) and name in EGRESS
                   and not _in_request(ctx, name, args) and ctx.extra.get("egress_n", 0) >= EGRESS_FREE)
    if over_budget:
        needs_confirm = True
    # money and contacts written after outside content: a planted text must never reach an invoice, a deal, a plan
    # or a client's address unseen (the red / white-hat rounds of issue #44)
    money_write = (ctx.tainted or echo) and t.risk >= Risk.REVERSIBLE and (
        t.group == "money" or name in ("contact_save", "contact_delete")) and not (
        name in _READS and _READS[name](args))
    reading = name in _READS and _READS[name](args)
    if ((ctx.tainted or echo) and name in TAINT_ASK and not reading) or made_up or money_write:
        needs_confirm = True
    leak = _leaks_private(ctx, name, args) if watch else ""
    if leak:
        needs_confirm = True  # outside content may be steering this: the user's own data must not go out unseen
    escalated = False
    if t.escalate is not None:
        try:
            escalated = bool(t.escalate(args))
        except Exception:
            escalated = True  # cannot tell: ask
    needs_confirm = needs_confirm or escalated
    forced = (escalated or bool(leak) or made_up or over_budget
              or ((ctx.tainted or echo) and name in TAINT_ASK and not reading) or money_write)
    if needs_confirm and name in ctx.cfg.auto_approve and not ctx.tainted and not forced and name not in NEVER_AUTO:
        needs_confirm = False
    if needs_confirm and name == "see_screen" and ctx.extra.get("screen_ok") and not ctx.tainted:
        # the user switched screen sharing ON in the app for this conversation (the eye button, visibly lit):
        # that is the consent. Only this one tool, and never after outside content entered the task.
        audit.log("confirm", tool=name, approved=True, summary="screen sharing is on")
        needs_confirm = False
    if needs_confirm:
        desc = t.summary(args) if t.summary else f"{name} {args}"
        # the card must show the action as it is: only real stored secrets are blanked (dlp.scrub); the pattern
        # redaction used for logs could hide part of a command ("token=x && del ...")
        from ..security.confirm import shown as _shown

        text = _shown(dlp.scrub(desc))
        notes = []
        if redact(text) != text:
            notes.append("parts of this look like passwords or keys - check the whole action carefully")
        if escalated:
            notes.append("asked because this writes where programs start by themselves, creates a program, or sets up "
                         "something that runs by itself")
        if origin == "private":
            notes.append("this address came only from your own files or mail - a planted document can contain links "
                         "meant to carry your data out")
        elif made_up:
            notes.append("this address was not in your request or in anything Vaelon read for this task")
        if over_budget:
            notes.append(f"Vaelon already contacted {ctx.extra.get('egress_n', 0)} outside services after reading your "
                         "own data in this task")
        if name == "run_command":
            from ..security.policy import STARTS_ITSELF

            if STARTS_ITSELF.search(str(args.get("command", ""))):
                notes.append("this command makes something start by itself later")
        if leak:
            notes.append(f"this sends text from your {leak} to an outside service")
        ctx.extra["card"] = desc  # what the user is shown for THIS call: a tool may check it is still what it does
        ok = ctx.approver(ConfirmRequest(name, text, ctx.tainted, "; ".join(notes)))
        audit.log("confirm", tool=name, approved=ok, summary=desc)
        if not ok:
            return "DENIED: the user did not approve this action. Do not retry; ask what they want instead."
    try:
        out = str(t.func(ctx, **args))
    except PolicyError as e:
        out = f"BLOCKED by policy: {e}"
    except TypeError as e:
        out = f"ERROR: bad arguments: {e}"
    except Exception as e:  # tools must never crash the agent
        out = f"ERROR: {type(e).__name__}: {e}"
    out = dlp.scrub(out)
    if t.untrusted:
        ctx.tainted = True
    is_private = bool(t.private or name in PRIVATE_TOOLS)
    failed = out.startswith(("ERROR", "BLOCKED", "DENIED"))
    note_urls(ctx, out, private=is_private)
    if name in EGRESS and not failed and ctx.extra.get("private_read"):  # counted from the first private read on
        ctx.extra["egress_n"] = ctx.extra.get("egress_n", 0) + 1
    if is_private and not failed:
        note_private(ctx, out)
        ctx.extra["private_read"] = True
    elif t.untrusted and not failed:
        # tokens a real outside source showed are not secrets - minus what this very call sent (no "washing" a
        # secret through an echo of the arguments)
        sent = _tokens(" ".join(str(v) for v in args.values()))
        before = set(ctx.extra.get("public_tokens", set()))
        note_public(ctx, out)
        ctx.extra["public_tokens"] = before | (ctx.extra["public_tokens"] - sent)
    audit.log("tool", tool=name, args=args, ok=not out.startswith(("ERROR", "BLOCKED", "DENIED")))
    if ctx.hooks:
        ctx.hooks.fire("post_tool", tool=name, args=args, result=out)
    out = out[:20000]
    if cache is not None and not out.startswith(("ERROR", "BLOCKED", "DENIED")):
        cache[ckey] = (time.time(), out)
        while len(cache) > CACHE_MAX:
            try:
                cache.pop(next(iter(cache)))
            except (StopIteration, KeyError, RuntimeError):
                break
    return out


def load_builtin() -> None:
    from . import coding, comms, create, extensions, files, github, knowledge, memory_tools, perception  # noqa: F401
    from . import folders, money, planner, security_tools, system, web  # noqa: F401
    from . import evolve  # noqa: F401
    from .. import evolution, learning  # noqa: F401


def load_plugins(directory: Path) -> list[str]:
    """Import approved plugins (*.py). Unapproved or modified files are skipped (see security/integrity.py)."""
    loaded = []
    if not directory.is_dir():
        return loaded
    for f in sorted(directory.glob("*.py")):
        if f.name.startswith("_"):
            continue
        if not integrity.is_trusted("plugins", f):  # only code you approved, byte for byte
            audit.log("plugin_untrusted_skipped", file=f.name)
            continue
        spec = importlib.util.spec_from_file_location(f"vaelon_plugin_{f.stem}", f)
        if not spec or not spec.loader:
            continue
        mod = importlib.util.module_from_spec(spec)
        try:
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            loaded.append(f.name)
        except Exception as e:
            audit.log("plugin_error", file=f.name, error=str(e))
    return loaded
