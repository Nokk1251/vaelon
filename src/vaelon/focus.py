"""Profiles: what the user mostly uses Vaelon for. OPTIONAL - like the "what do you like?" picker of a streaming app:
pick none, one or several, change it any time in Settings.

A profile changes three small things and nothing else:
- a few of its everyday tools are always in the toolbox, so they work without the trigger words (`starter`);
- one short line tells the model how this user likes to be helped (`hint`, sent with the request, never in the cached
  system prompt);
- its examples come first in the menu (`examples`).
Nothing becomes unreachable: every other tool is still added by its words or by `more_tools`. A profile never grants
anything - approvals, company roles and folders stay exactly as they are.
"""
from __future__ import annotations

PROFILES: dict[str, dict] = {
    "business": {
        "title": "Business",
        "blurb": "Bills, invoices, budget, deals, meetings and documents for your work.",
        "starter": ["bills_summary", "bill_add", "expense_add", "budget_report", "deals_list", "event_add", "agenda"],
        "hint": "The user runs a business: be exact and brief, money in euro, and offer to record what they mention "
                "(a bill, an invoice, a deal, a meeting) instead of only talking about it.",
        "examples": ["Bills and invoices", "Budget", "Deals", "Bank statement"],
    },
    "learning": {
        "title": "Learning",
        "blurb": "Lessons, exam plans, explanations and practice tests.",
        "starter": ["study_plan", "event_add", "wiki", "create_document"],
        "hint": "The user is learning: explain step by step with a simple example, check understanding, and offer "
                "practice questions or a study plan.",
        "examples": ["Life (Vaelon thinks one step ahead)", "Knowledge", "Memory and learning"],
    },
    "coding": {
        "title": "Coding",
        "blurb": "Write, check and explain code; work with files and projects.",
        "starter": ["code_task", "fs_list", "fs_read", "fs_search"],
        "hint": "The user writes code: give complete, working code first, then a short explanation; name the risks "
                "of what you change.",
        "examples": ["Code", "Files and computer"],
    },
    "creator": {
        "title": "Creator",
        "blurb": "Reports, presentations, spreadsheets, podcasts and research.",
        "starter": ["create_document", "create_presentation", "create_spreadsheet", "create_audio"],
        "hint": "The user makes content: when they describe something to make, make the file (document, slides, "
                "table, audio) and keep it looking human-made.",
        "examples": ["Create files", "Research, reminders, vision", "Internet"],
    },
    "life": {
        "title": "Everyday life",
        "blurb": "Reminders, calendar, birthdays, household budget and the weather.",
        "starter": ["remind", "event_add", "agenda", "expense_add"],
        "hint": "Help with everyday life and think one step ahead: offer a reminder or a calendar entry when a date "
                "or a task comes up.",
        "examples": ["Life (Vaelon thinks one step ahead)", "Live data (instant)", "Budget"],
    },
}
MAX = len(PROFILES)


def clean(value) -> list[str]:
    """A valid profile list from what the app sent (raises ValueError on anything else)."""
    if not isinstance(value, list) or len(value) > MAX:
        raise ValueError("profiles must be a list of up to %d names" % MAX)
    out: list[str] = []
    for v in value:
        if not isinstance(v, str) or v not in PROFILES:
            raise ValueError("unknown profile")
        if v not in out:
            out.append(v)
    return out


def chosen(cfg) -> list[str]:
    """The user's profiles, in a fixed order (so the toolbox - and the model's prompt cache - stays the same)."""
    have = getattr(cfg, "profiles", None) or []
    return [p for p in PROFILES if p in have]


def starter_tools(cfg) -> set[str]:
    from .tools import registry

    return {n for p in chosen(cfg) for n in PROFILES[p]["starter"] if n in registry.REGISTRY}


def hint(cfg) -> str:
    """One line for the user message (empty when no profile is chosen)."""
    lines = [PROFILES[p]["hint"] for p in chosen(cfg)]
    return ("USER FOCUS: " + " ".join(lines)) if lines else ""


def order_examples(examples: dict, cfg) -> dict:
    """The menu's examples with the chosen profiles' sections first (the rest keep their order)."""
    first = [s for p in chosen(cfg) for s in PROFILES[p]["examples"] if s in examples]
    first = list(dict.fromkeys(first))
    return {**{s: examples[s] for s in first}, **{s: v for s, v in examples.items() if s not in first}}


def listing(cfg) -> list[dict]:
    have = set(chosen(cfg))
    return [{"name": n, "title": p["title"], "blurb": p["blurb"], "on": n in have} for n, p in PROFILES.items()]
