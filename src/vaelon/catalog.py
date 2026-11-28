"""Everything Vaelon can do, in one structure: shown by the app's menu (☰). """
from __future__ import annotations

from . import config, skills

GROUP_TITLES = {
    "knowledge": "Knowledge and live data", "web": "Internet", "files": "Files", "system": "Computer",
    "comms": "Communication", "memory": "Memory", "learning": "Self-learning", "evolution": "Self-improvement",
    "evolve": "Self-improvement", "perception": "Vision and documents", "security": "Security",
    "coding": "Coding", "agents": "Agents", "core": "Core", "general": "General", "create": "Create files",
    "planner": "Reminders and schedule", "money": "Money: bills, budget, deals, invoices", "mcp": "Connected tools (MCP)",
}

EXAMPLES = {
    "Live data (instant)": [
        "How did Nvidia stock do over the last 3 days?", "What is the bitcoin price?", "What's the weather in London?",
        "EUR to USD exchange rate", "Convert 250 USD to EUR", "Gold price on the market today",
    ],
    "Knowledge": [
        "What is a black hole?", "Who was Nikola Tesla?", "Find scientific papers about quantum computers",
        "Recommend books like Dune", "What is Japan's GDP?", "Latest news about artificial intelligence",
    ],
    "Files and computer": [
        "Show the files in Downloads", "Find all PDF files in Documents", "How much RAM is free?",
        "Which programs use the most memory?", "Open Notepad", "Sort Downloads by file type",
    ],
    "Internet": [
        "Search the web for the best laptops of 2026", "Read https://example.com and summarise it",
        "Download the file from <link> to Downloads",
    ],
    "Code": [
        "Write a Python script that renames photos by date", "Check main.py for errors",
        "Find a FastAPI example with JWT on GitHub",
    ],
    "Security": [
        "Check my computer for security problems", "Is the link <link> safe?", "Scan setup.exe for viruses",
        "Are there vulnerabilities in requests 2.25?",
    ],
    "Create files": [
        "Write a one-page report about solar energy and save it as PDF",
        "Make an Excel table with a monthly budget for a student",
        "Create a 6-slide presentation about black holes",
        "Make a two-voice podcast about the history of the internet",
    ],
    "Research, reminders, vision": [
        "/research the state of solid-state batteries in 2026", "Remind me in 20 minutes to call mum",
        "Remind me tomorrow at 9 to pay the electricity bill", "Every day at 08:00 give me a morning briefing",
        "(attach a picture with the paperclip) What is in this picture?",
    ],
    "Bills and invoices": [
        "Add a bill: electricity 45.20 EUR due 25.11", "What bills do I have to pay?", "I paid the electricity bill",
        "(attach a bill's PDF or photo) Add this bill", "How much did I pay for electricity this year?",
        "Make an invoice for Acme Ltd: Web design | 1 | 500", "Who owes me?",
    ],
    "Budget": [
        "Spent 30 EUR on groceries", "Got paid 2000 EUR salary", "Set a budget of 400 EUR for groceries",
        "How is my budget?", "How much is left for eating out?", "How much did I spend on fuel this month?",
    ],
    "Life (Vaelon thinks one step ahead)": [
        "I have a history exam in 4 days", "Topics: WW1, WW2, the Cold War; 1 hour a day",
        "Mum's birthday is on 12 March", "I forgot Peter's birthday, it was yesterday", "Our anniversary is on 20 June",
    ],
    "Bank statement": [
        "(attach the statement CSV from your online banking) Import this bank statement",
        "Load demo data", "Remove the demo data",
    ],
    "Deals": [
        "New deal with Acme Ltd: website 5000 EUR", "Move Acme to proposal", "Follow up with Acme on Friday",
        "We won the Acme deal", "Make the invoice for the Acme deal", "How are my deals going?",
    ],
    "Communication": [
        "Email mum that I'll be late", "Read my latest emails", "Call +44…",
    ],
    "Memory and learning": [
        "Remember that my birthday is on 13 July", "What do you know about me?", "Learn about electric cars",
        "Learn a skill: how to write a weekly report",
    ],
}

SLASH = [
    ("/help", "the help page: everything explained, and feedback"), ("/menu", "this menu"),
    ("/feedback", "write an idea or a problem (saved as a file, nothing is sent)"), ("/voice", "voice designer"), ("/memory", "what Vaelon knows about you"),
    ("/new", "start a new conversation (the old ones stay in the list)"),
    ("/chats", "your conversations: open, rename or delete one"),
    ("/calendar", "your calendar: the next two weeks, add or cancel an appointment, export .ics"),
    ("/bills", "bills to pay, paid bills, the invoices you issue and your business details"),
    ("/budget", "this month's income and spending against your limits"),
    ("/cashflow", "money in and out over the next weeks, and a warning when it may run short"),
    ("/quotes", "quotes to clients; an accepted one becomes an invoice in one step"),
    ("/recurring", "invoices that repeat (retainers, rent): made on their day, never sent by themselves"),
    ("/overdue", "payment reminder drafts for overdue invoices: you check and send them"),
    ("/deals", "your sales pipeline: deals by stage, next steps, won and lost"),
    ("/company", "company mode: companies, people and roles, the journal of who changed what"),
    ("vaelon company status | enable | disable", "company mode: people with roles, separate companies, the journal"),
    ("vaelon demo load | remove", "made-up data to try Money and the calendar (only the demo is ever removed)"),
    ("/clear", "erase the messages of this conversation"),
    ("/talk", "hands-free conversation: speak, listen, interrupt"), ("/stop", "cancel every running task"),
    ("/research <topic>", "deep research: several searches, many pages, a report with sources"),
    ("/settings", "your name, profiles, the model, API keys, voice, connected tools"),
    ("/speed", "show how long each part of an answer took (on / off)"),
    ("/about", "author, license, version"),
]

CLI = [
    ("vaelon app", "opens the app"), ("vaelon chat", "chat in the terminal"),
    ("vaelon run \"task\"", "a single task"), ("vaelon voice", "voice control (\"Vaelon, ...\")"),
    ("vaelon voice-setup", "downloads the local neural voices"),
    ("vaelon voice-design --preset titan", "changes the voice (vaelon, butler, titan, machine, radio, ghost, clean)"),
    ("vaelon provider", "list of model providers: local, groq, gemini, openrouter, cerebras, mistral ..."),
    ("vaelon provider groq", "switch to a fast free cloud model"),
    ("vaelon key set GROQ_API_KEY", "stores a key ENCRYPTED"), ("vaelon key list", "which keys are set"),
    ("vaelon models", "which models your key allows"), ("vaelon learn \"topic\"", "researches a topic and remembers it"),
    ("vaelon study", "self-study from the web and GitHub"),
    ("vaelon schedule add --daily 08:00 \"morning briefing\"", "scheduled tasks"),
    ("vaelon memory list|search|wipe", "memory"), ("vaelon skills", "all skills"),
    ("vaelon tools", "all tools"), ("vaelon doctor", "system check"),
    ("vaelon integrity verify|sign", "code signature"), ("vaelon evolution history|rollback", "self-changes"),
    ("vaelon telegram", "control from your phone"), ("vaelon token", "access key for the app"),
    ("vaelon mcp add NAME -- command", "connect an outside tool server (MCP); also: mcp list|allow|refresh|remove"),
    ("vaelon about", "author, license, version"), ("vaelon update", "check for a newer release"),
]






def build(memory=None, lang: str = "en", personal: bool = True) -> dict:
    from . import conversation, focus, profile, providers
    from .tools import registry

    registry.load_builtin()
    titles = GROUP_TITLES
    tools = [{"name": t.name, "description": t.description, "group": titles.get(t.group, t.group),
              "risk": t.risk.name.lower(), "args": list(t.params)}
             for t in sorted(registry.REGISTRY.values(), key=lambda t: (t.group, t.name))]
    learned_dir = config.HOME / "skills"
    learned = {f.stem for f in learned_dir.glob("*.md")} if learned_dir.is_dir() else set()
    # the menu lists the English trigger words (every language keeps working - the words are only shown in English)
    sk = [{"name": s.name, "description": s.description,
           "triggers": [w for w in s.triggers if w.isascii()][:8], "learned": s.name in learned
           or s.name.startswith("learned-")} for s in skills.load_all()]
    cfg = config.Config.load()
    keys = {}
    for p in providers.PRESETS.values():
        if p["api_key_env"]:
            keys[p["api_key_env"]] = bool(config.env(p["api_key_env"]))
    for name in providers.EXTRA_KEYS:
        keys[name] = bool(config.env(name))
    stats = memory.stats() if memory is not None else {}
    return {
        "tools": tools, "skills": sk, "examples": focus.order_examples(EXAMPLES, cfg) if personal else EXAMPLES,
        "profiles": [p["name"] for p in focus.listing(cfg) if p["on"]] if personal else [],
        "slash": SLASH, "cli": CLI,
        "memory": ({"profile": profile.load(), "facts": stats, "recent": [t for _, t in memory.recent(12, kind="user")]
                    if memory is not None else [], "conversation": conversation.count(), "learned_skills": len(learned)}
                   if personal else {"profile": {}, "facts": {}, "recent": [], "conversation": 0, "learned_skills": 0}),
        "model": {"provider": cfg.provider, "model": cfg.model, "local": cfg.is_local},
        "keys": keys,
        "about": about(),
    }


def about() -> dict:
    """The Appropriate Legal Notices (GPL-3.0 section 0 + the attribution term in NOTICE). Keep them visible."""
    from . import ABOUT, __author__, __author_url__, __license__, __source__, __version__

    return {"version": __version__, "author": __author__, "author_url": __author_url__, "license": __license__,
            "source": __source__,
            "text": ABOUT}
