"""Tool routing: show the model only the tools a request needs.

Fewer tools = a shorter prompt (faster on CPU) and fewer wrong choices (smarter on small models).
The model can always ask for more with `more_tools`, so nothing becomes unreachable.
"""
from __future__ import annotations

from .tools import registry

CORE = {"now", "remember", "recall", "undo", "more_tools", "delegate"}
# The everyday toolbox. It is ALWAYS the same, so the prompt prefix is identical from one request to the next and
# Ollama reuses its cache: on a CPU that turns ~15-30 s of prompt reading into ~1-3 s.
STABLE = CORE | {"web_search", "web_fetch", "wiki", "weather", "stock_quote", "crypto_price", "exchange_rate",
                 "tech_news", "science_papers", "book_search"}
COVERED = {"web", "knowledge", "memory"}  # groups whose everyday tools are already in STABLE

GROUP_WORDS = {
    "files": "файл папк документ запиши запази изтрий премести преименувай копирай downloads desktop file folder "
             "directory save delete remove move rename copy path",
    "web": "търси намери интернет сайт страница новини свали линк google search find web internet site page news "
           "download url http link",
    "system": "процес приложение програма отвори пусни команда терминал cpu ram памет система компютър "
              "process app open launch run command terminal shell system computer kill",
    "comms": "мейл имейл писмо sms съобщение обади позвъни звънни контакт email mail message call contact",
    "memory": "помни запомни спомни забрави remember recall forget memory",
    "learning": "научи учи умение проучи learn study skill research teach",
    "evolution": "себе си собствен код подобри се пренапиши разширени плъгин yourself your own code improve "
                 "rewrite self extension plugin evolve",
    "perception": "pdf docx документ екран снимка изображение виж погледни прочети прикачен attached screen image picture photo "
                  "look see read document",
    "security": "уязвим cve exploit пакет vulnerab вирус зловред сканирай сигурност безопас пробив хак фишинг virus malware scan security safe "
                "breach hack phishing audit threat",
    "coding": "код програм скрипт функция бъг тест python javascript typescript code program script function bug "
              "test refactor compile",
    "agents": "делегирай агент delegate agent",
    "planner": "напомни напомняне припомни график насрочи всеки ден всяка сутрин всяка вечер таймер аларма календар "
               "среща срещи ангажимент събитие програма предстои отложи премести remind reminder schedule scheduled "
               "every day every morning every hour daily timer alarm calendar meeting appointment agenda event .ics",
    "money": "сметк фактур платих плащане плати дълж разход разходи бюджет наем застраховк данък абонамент "
             "ддс еик похарч харча заплат лимит приход bill bills invoice invoices paid owe owes expense expenses spent "
             "spend budget rent utilit receipt vat income salary limit сделк оферт клиент deal deals pipeline "
             "proposal client lead извлечение statement bank банк",
    "create": "документ доклад отчет word docx pdf excel xlsx таблица презентация слайд powerpoint pptx аудио подкаст "
              "запис озвучи прочети на глас document report letter spreadsheet presentation slides deck audio podcast "
              "narrate read aloud recording",
    "knowledge": "какво е кой е обясни уикипедия времето прогноза валута курс крипто биткойн акци борса инвест "
                 "държава столица икономик ввп инфлация наука изследван статия книга автор игра игри новини "
                 "what is who is explain wikipedia weather forecast currency rate crypto bitcoin stock market "
                 "invest country capital economy gdp inflation science paper research book author game games news",
}
_WORDS = {g: [w for w in ws.split() if len(w) >= 3] for g, ws in GROUP_WORDS.items()}  # no 1-2 letter noise
DEFAULT_GROUPS = {"web", "knowledge"}  # general questions mostly need lookups; anything else is one `more_tools` away


def groups_for(text: str) -> set[str]:
    import re

    starts = " " + re.sub(r"[^\w.]+", " ", text.lower())  # " word word"; a group word must start a word
    return {g for g, ws in _WORDS.items() if any(" " + w in starts for w in ws)}


def tools_in(groups: set[str]) -> set[str]:
    alias = {"evolve": "evolution"}
    return {n for n, t in registry.REGISTRY.items() if alias.get(t.group, t.group) in groups}


def route(request: str, cfg=None) -> set[str]:
    """The stable toolbox (+ the starter tools of the user's profiles - the same every turn, so the prompt cache still
    works), plus a specialised group only when the request clearly needs it."""
    from . import focus

    extra = groups_for(request) - COVERED
    stable = {n for n in STABLE if n in registry.REGISTRY}
    if cfg is not None:
        stable |= focus.starter_tools(cfg)
    return stable | tools_in(extra) if extra else stable


def expand(active: set[str], need: str) -> set[str]:
    """Called by `more_tools`: add the groups matching `need`, or everything if nothing matches."""
    groups = groups_for(need)
    return active | (tools_in(groups) if groups else set(registry.REGISTRY))


@registry.tool("more_tools", "Unlock more tools when none of the listed ones fits (describe what you need)",
               {"need": "what kind of tool you need"}, group="core")
def _more_tools_stub(ctx, need):  # handled inside Agent.run
    return "handled by the agent loop"
