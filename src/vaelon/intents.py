"""Direct intents: common questions answered from LIVE data without asking the model which tool to use.

Why: small local models often refuse ("I cannot access real-time data") even when the right tool is listed,
and every model round-trip costs seconds on a CPU. For clear requests - stock/crypto prices, weather, exchange
rates, "remember that...", "what do you know about me" - Vaelon calls the free source itself and answers at once
(well under a second plus network time). Encyclopedia questions are pre-fetched and handed to the model so its
answer is grounded. Anything unclear falls through to the normal agent loop.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import profile


@dataclass
class Hit:
    answer: str | None = None  # final answer, no model needed
    tool: str | None = None  # or: run this tool first, then let the model answer from the result
    args: dict = field(default_factory=dict)
    outside: bool = False  # the answer shows words from an imported file (.ics, a bill read from a file, a bank line)


class _Outside(str):
    """A fast answer that shows imported text: the turn counts as outside content (registry.outside_shown)."""


def _shows(text: str, records) -> str:
    return _Outside(text) if any(isinstance(r, dict) and (r.get("src") or r.get("file") or r.get("ref"))
                                 for r in records) else text


def is_bg(text: str) -> bool:
    return bool(re.search(r"[\u0400-\u04FF]", text))


_EN = set("the a an and or is are was were be to of in on for with my me you your i can could would should what "
          "how why which who when where do does did please recommend tell give show find best this that it not "
          "have has about from at as by if than more most hello hi hey thanks thank yes no ok okay good morning "
          "evening night bye sorry help make write explain".split())
_OTHER = set("der die das und ist nicht sind für mit ein eine ich sie wir auch oder aber wie les des est une "
             "pour avec dans que qui pas sont los las el y por para una con como del het een niet zijn".split())


def lang_of(text: str) -> str | None:
    """'bg' (Cyrillic), 'en' (clearly English) or None (unknown) - decided by the computer, not the model."""
    if is_bg(text):
        return "bg"
    words = re.findall(r"[a-zäöüßàâçéèêëîïôûùüÿñæœ']+", text.lower())
    if not words:
        return None
    en, other = lang_counts(text)
    return "en" if en >= 1 and en > other else None


def lang_counts(text: str) -> tuple[int, int]:
    """(English function words, other-European function words) - used to spot an answer in the wrong language."""
    words = re.findall(r"[a-zäöüßàâçéèêëîïôûùüÿñæœ']+", (text or "").lower())
    return sum(w in _EN for w in words), sum(w in _OTHER for w in words)


def _num(x: float) -> str:
    return f"{x:,.2f}".replace(",", " ") if abs(x) >= 1 else f"{x:.4g}"


# ---------------------------------------------------------------- stocks
STOCK_RX = re.compile(r"(?i)акци|борс|котировк|\bstocks?\b|\bshares?\b|share price|\bticker\b|\bетф\b|\betf\b|"
                      r"wall street|\bindices\b|s&p|nasdaq|dow jones")
COMPANIES = {
    "нвидия": "NVDA", "nvidia": "NVDA", "тесла": "TSLA", "tesla": "TSLA", "епъл": "AAPL", "apple": "AAPL",
    "майкрософт": "MSFT", "microsoft": "MSFT", "гугъл": "GOOGL", "google": "GOOGL", "алфабет": "GOOGL",
    "амазон": "AMZN", "amazon": "AMZN", "мета": "META", "фейсбук": "META", "facebook": "META",
    "нетфликс": "NFLX", "netflix": "NFLX", "амд": "AMD", "интел": "INTC", "intel": "INTC", "оракъл": "ORCL",
    "палантир": "PLTR", "palantir": "PLTR", "кока-кола": "KO", "макдоналдс": "MCD", "дисни": "DIS",
    "s&p 500": "^GSPC", "s&p": "^GSPC", "с&п": "^GSPC", "насдак": "^IXIC", "nasdaq": "^IXIC", "дау": "^DJI",
    "dow jones": "^DJI", "злато": "GC=F", "gold": "GC=F", "петрол": "CL=F", "нефт": "CL=F", "oil": "CL=F",
    "сребро": "SI=F", "silver": "SI=F",
}
EN_STOP = set("stock stocks share shares price prices the how what is are was doing did last days day week month "
              "year today of for and on in at me tell show give performance trend etf ticker market quote about "
              "has have been going past".split())
NOT_TICKERS = {"ETF", "USD", "EUR", "BGN", "CEO", "AI", "IPO"}


def _days(low: str) -> int:
    m = re.search(r"(\d+)\s*(?:търговски\s+)?(?:дни|дена|ден|days?|trading days)", low)
    if m:
        return max(1, min(int(m.group(1)), 250))
    if re.search(r"седмиц|week", low):
        return 5
    if re.search(r"месец|month", low):
        return 21
    if re.search(r"година|year", low):
        return 250
    if re.search(r"днес|today", low):
        return 1
    return 5


BG_END = r"(?:та|то|ът|ят|а|я|ия)?(?!\w)"  # Bulgarian article/case endings: Теслата, Нвидия


def _ticker(request: str, K) -> str | None:
    low = request.lower()
    for name, sym in sorted(COMPANIES.items(), key=lambda kv: -len(kv[0])):
        if re.search(r"(?<!\w)" + re.escape(name) + BG_END, low):
            return sym
    for tok in re.findall(r"(?<![\w$])\$?([A-Z]{2,5})(?!\w)", request):
        if tok not in NOT_TICKERS:
            return tok
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z.&-]{2,}", request) if w.lower() not in EN_STOP]
    if words:
        if MARKET_RX.search(request):  # "the stock market today" is about the market, not a company called "Today"
            return None
        return K.resolve_ticker(" ".join(words[:3]))
    return None


MARKET_RX = re.compile(r"(?i)stock market|the market|markets|wall street|indices|indexes|борсата|борсите|пазарите|индекс")
INDICES = [("^GSPC", "S&P 500"), ("^IXIC", "Nasdaq"), ("^DJI", "Dow Jones")]


def _market(bg: bool, K) -> str | None:
    """'How is the stock market?' -> the three main US indices, live."""
    lines, source = [], "Yahoo Finance"
    for sym, label in INDICES:
        h = K.stock_history(sym, 1)
        if not h or len(h["closes"]) < 1:
            continue
        source = h.get("source") or source
        rows = h["closes"]
        last = h.get("price") or rows[-1][1]
        prev = rows[-2][1] if len(rows) > 1 else rows[0][1]
        chg = (last / prev - 1) * 100 if prev else 0.0
        lines.append(f"• {label}: {_num(last)} ({chg:+.2f}%)")
    if not lines:
        return None
    head = "Пазарите сега (спрямо предишното затваряне):" if bg else "Markets now (vs. previous close):"
    tail = (f"Данни от {source} - информация, не инвестиционен съвет." if bg
            else f"{source} data - information, not investment advice.")
    return "\n".join([head] + lines + [tail])


def _stock(request: str, bg: bool, K) -> str | None:
    sym = _ticker(request, K)
    if not sym:
        return _market(bg, K) if MARKET_RX.search(request) else None
    n = _days(request.lower())
    h = K.stock_history(sym, n)
    if not h or not h["closes"]:
        return None
    rows, cur, source = h["closes"], h["currency"], h.get("source") or "Yahoo Finance"
    base, shown = (rows[0], rows[1:]) if len(rows) > n else (rows[0], rows)
    last = shown[-1][1]
    chg = (last / base[1] - 1) * 100 if base[1] else 0.0
    head = (f"{h['name']} ({h['symbol']}) - последни {len(shown)} търговски дни:" if bg
            else f"{h['name']} ({h['symbol']}) - last {len(shown)} trading days:")
    lines = [head] + [f"• {d}: {_num(c)} {cur}" for d, c in shown[-10:]]
    price = h.get("price") or last
    if bg:
        lines.append(f"Промяна: {chg:+.2f}% ({_num(base[1])} → {_num(last)}). Текуща цена: {_num(price)} {cur}.")
        lines.append(f"Данни от {source} - информация, не инвестиционен съвет.")
    else:
        lines.append(f"Change: {chg:+.2f}% ({_num(base[1])} → {_num(last)}). Current price: {_num(price)} {cur}.")
        lines.append(f"{source} data - information, not investment advice.")
    return "\n".join(lines)


# ---------------------------------------------------------------- crypto
COINS = {"биткойн": "bitcoin", "bitcoin": "bitcoin", "btc": "bitcoin", "етериум": "ethereum", "ethereum": "ethereum",
         "eth": "ethereum", "солана": "solana", "solana": "solana", "доджкойн": "dogecoin",
         "dogecoin": "dogecoin", "doge": "dogecoin", "рипъл": "ripple", "xrp": "ripple", "кардано": "cardano",
         "cardano": "cardano", "лайткойн": "litecoin", "litecoin": "litecoin", "bnb": "binancecoin",
         "toncoin": "the-open-network", "полкадот": "polkadot", "polkadot": "polkadot"}
PRICE_RX = re.compile(r"(?i)цена|цената|струва|курс|колко|върви|вървят|днес|price|worth|cost|how much|trading|today|now")


def _crypto(request: str, bg: bool, K) -> str | None:
    low = request.lower()
    ids = []
    for word, cid in COINS.items():
        if re.search(r"(?<!\w)" + re.escape(word) + BG_END, low) and cid not in ids:
            ids.append(cid)
    if not ids or not PRICE_RX.search(request):
        return None
    data = K._get("https://api.coingecko.com/api/v3/simple/price",
                  {"ids": ",".join(ids[:5]), "vs_currencies": "usd,eur", "include_24hr_change": "true"})
    lines = []
    for cid in ids[:5]:
        d = data.get(cid)
        if not d:
            continue
        ch = d.get("usd_24h_change") or 0.0
        name = cid.replace("-", " ").title()
        lines.append(f"{name}: {_num(d['usd'])} USD ({_num(d['eur'])} EUR), "
                     + (f"за 24 ч: {ch:+.2f}%." if bg else f"24h: {ch:+.2f}%."))
    if not lines:
        return None
    lines.append("Източник: CoinGecko - информация, не инвестиционен съвет." if bg
                 else "Source: CoinGecko - information, not investment advice.")
    return "\n".join(lines)


# ---------------------------------------------------------------- weather
WEATHER_RX = re.compile(r"(?i)времето|прогноз|температур|ще вали|вали ли|градус|weather|forecast|temperature|will it rain")
NOT_PLACES = {"утре", "днес", "вдругиден", "момента", "седмицата", "уикенда", "времето", "сега", "града", "нас",
              "today", "tomorrow", "the", "now", "weekend", "this", "my", "here"}
WMO_BG = {0: "ясно", 1: "предимно ясно", 2: "разкъсана облачност", 3: "облачно", 45: "мъгла", 48: "мъгла",
          51: "ръми", 53: "ръми", 55: "ръми", 61: "слаб дъжд", 63: "дъжд", 65: "силен дъжд", 66: "леден дъжд",
          67: "леден дъжд", 71: "слаб сняг", 73: "сняг", 75: "силен сняг", 77: "снежни зърна", 80: "превалявания",
          81: "превалявания", 82: "силни превалявания", 85: "снеговалежи", 86: "снеговалежи", 95: "гръмотевици",
          96: "гръмотевици с град", 99: "гръмотевици с град"}
WMO_EN = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "fog", 51: "drizzle",
          53: "drizzle", 55: "drizzle", 61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain",
          67: "freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "showers",
          81: "showers", 82: "heavy showers", 85: "snow showers", 86: "snow showers", 95: "thunderstorm",
          96: "thunderstorm with hail", 99: "thunderstorm with hail"}


def _place(request: str) -> str | None:
    for m in re.finditer(r"(?i:\bвъв|\bв|\bза|\bin|\bfor|\bat)\s+([A-Za-zА-Яа-яЁё][\w-]+(?:[ -][A-ZА-Я][\w-]+)?)", request):
        cand = m.group(1).strip()
        if cand.lower() not in NOT_PLACES:
            return cand
    return None


def _weather(request: str, bg: bool, K, work_only: bool = False) -> str | None:
    place = _place(request) or (None if work_only else profile.load().get("city"))  # never the owner's city for others
    if not place:
        return None
    w = K.weather_data(place, "bg" if bg else "en")
    if not w:
        return None
    now, daily = w["now"], w["daily"]
    names = WMO_BG if bg else WMO_EN
    desc = names.get(now.get("weather_code"), "")
    t, a, wind = now.get("temperature_2m"), now.get("apparent_temperature"), now.get("wind_speed_10m")
    where = f"{w['place']}, {w['country']}".strip(", ")
    if bg:
        out = [f"{where}: сега {t:.0f}°C (усеща се {a:.0f}°C), {desc}, вятър {wind:.0f} км/ч."]
        labels = ["Днес", "Утре", "Вдругиден"]
    else:
        out = [f"{where}: now {t:.0f}°C (feels like {a:.0f}°C), {desc}, wind {wind:.0f} km/h."]
        labels = ["Today", "Tomorrow", "Day after"]
    for i, lab in enumerate(labels):
        try:
            lo, hi = daily["temperature_2m_min"][i], daily["temperature_2m_max"][i]
            rain = daily["precipitation_probability_max"][i]
            code = names.get(daily["weather_code"][i], "")
        except (KeyError, IndexError, TypeError):
            break
        out.append(f"{lab}: {lo:.0f}…{hi:.0f}°C, {code}" + (f", валежи {rain}%" if bg else f", rain {rain}%")
                   if rain is not None else f"{lab}: {lo:.0f}…{hi:.0f}°C, {code}")
    return "\n".join(out)


# ---------------------------------------------------------------- exchange rates
CURRENCIES = [("евро", "EUR"), ("евра", "EUR"), ("euro", "EUR"), ("долар", "USD"), ("dollar", "USD"),
              ("паунд", "GBP"), ("британски лири", "GBP"), ("pound", "GBP"), ("швейцарски франк", "CHF"),
              ("франк", "CHF"), ("йен", "JPY"), ("yen", "JPY"), ("юан", "CNY"), ("yuan", "CNY"), ("злот", "PLN"),
              ("турски лири", "TRY"), ("турска лира", "TRY"), ("румънски леи", "RON"), ("леи", "RON"),
              ("лева", "BGN"), ("лев", "BGN"), ("крона", "SEK"), ("forint", "HUF"), ("форинт", "HUF")]
ISO = {"EUR", "USD", "GBP", "CHF", "JPY", "CNY", "PLN", "TRY", "RON", "BGN", "SEK", "NOK", "DKK", "HUF", "CZK",
       "CAD", "AUD", "NZD", "INR", "BRL", "MXN", "ZAR", "KRW", "SGD", "HKD", "ILS", "ISK", "THB", "IDR", "PHP", "MYR"}
FX_RX = re.compile(r"(?i)курс|обмен|обърни|превърни|exchange|convert|\brate\b")
BGN_PER_EUR = 1.95583  # fixed conversion rate; Bulgaria joined the euro on 1 Jan 2026


def _currencies(request: str) -> list[str]:
    low = request.lower()
    hits = []
    for word, code in CURRENCIES:
        for m in re.finditer(r"(?<!\w)" + re.escape(word), low):
            hits.append((m.start(), code))
    for m in re.finditer(r"\b([A-Z]{3})\b", request):
        if m.group(1) in ISO:
            hits.append((m.start(), m.group(1)))
    out = []
    for _, code in sorted(hits):
        if code not in out:
            out.append(code)
    return out


def _fx(request: str, bg: bool, K) -> str | None:
    cur = _currencies(request)
    if not cur or not (FX_RX.search(request) or len(cur) >= 2) or STOCK_RX.search(request):
        return None
    base = cur[0]
    to = cur[1] if len(cur) > 1 else ("USD" if base == "EUR" else "EUR")
    m = re.search(r"\d{1,3}(?:[ \u00a0.,]\d{3})+(?:[.,]\d{1,2})?(?!\d)|\d+(?:[.,]\d+)?", request)
    try:
        from .bills import cents

        amount = cents(m.group(0)) / 100 if m else 1.0  # "1,000 USD", "1 500 евро", "1.234,56"
    except (ValueError, ImportError):
        amount = float(m.group(0).replace(",", ".").replace(" ", "")) if m else 1.0

    def eur_rate(code: str, rates: dict) -> float | None:  # units of `code` per 1 EUR
        return 1.0 if code == "EUR" else BGN_PER_EUR if code == "BGN" else rates.get(code)

    need = [c for c in (base, to) if c not in ("EUR", "BGN")]
    data = K._get("https://api.frankfurter.app/latest", {"from": "EUR", "to": ",".join(need)}) if need \
        else {"rates": {}, "date": ""}
    rb, rt = eur_rate(base, data["rates"]), eur_rate(to, data["rates"])
    if not rb or not rt:
        return None
    value = amount / rb * rt
    date = data.get("date", "")
    note = ""
    if "BGN" in (base, to):
        note = (" (фиксиран курс 1 EUR = 1.95583 BGN; от 1.01.2026 в България се плаща в евро)" if bg
                else " (fixed rate 1 EUR = 1.95583 BGN; Bulgaria uses the euro since 1 Jan 2026)")
    if bg and re.fullmatch(r"\d{4}-\d\d-\d\d", date):
        date = ".".join(reversed(date.split("-")))
    src = (f"ЕЦБ, {date}" if bg else f"ECB, {date}") if date else ""
    val = f"{value:.4f}" if value < 10 else _num(value)
    return f"{amount:g} {base} = {val} {to}" + (f" ({src})" if src else "") + note + "."


# ---------------------------------------------------------------- memory & self
REMEMBER_RX = re.compile(r"(?is)^\s*(?:запомни|запиши си|remember|note)\s*(?:,|:)?\s*(?:че\s+|that\s+)?(.{3,400}?)\s*[.!]?\s*$")
ABOUT_ME_RX = re.compile(r"(?i)какво (?:знаеш|помниш) за мен|какво си научил за мен|кой съм аз|"
                         r"what do you (?:know|remember) about me|who am i")
HELP_RX = re.compile(r"(?i)^\s*(?:/help|/помощ|помощ|help|какво можеш(?: да правиш)?|what can you do|команди|menu|меню)\s*[?!.]*\s*$")
WIKI_RX = re.compile(r"(?i)^\s*(?:какво е|какво са|какво означава|кой е|коя е|кои са|кой беше|коя беше|кое е|"
                     r"разкажи ми за|обясни ми какво е|what is|what are|what was|who is|who was|who were|"
                     r"tell me about|explain what)\s+(.{2,80}?)\s*\??\s*$")
# "what is X" asks for a concept (stable knowledge); "who is X" asks about a person (it changes, it is misremembered)
CONCEPT_RX = re.compile(r"(?i)^\s*(?:какво е|какво са|какво означава|обясни ми какво е|what is|what are|explain what)\s")
WIKI_SKIP = re.compile(r"(?i)\b(ти|теб|твоят|твоето|vaelon|вейлон|you|your|времето|часът|датата|днес|това|този|тази|"
                       r"най-добр\w*|по-добр\w*|разликата|сега|текущ\w*|последн\w*|цена\w*|"
                       r"weather|time|date|today|this|that|best|better|difference|current|currently|latest|now|"
                       r"recent|price|state of|news)\b")

HELP_BG = """Мога да:
• отговарям с живи данни: акции, крипто, валутни курсове, времето, Уикипедия, научни статии, книги, новини
• работя с файлове: търся, чета, пиша, местя, трия (с потвърждение и undo)
• търся и сваля от интернет (всеки линк и файл се проверява за вируси)
• пиша и проверявам код, проучвам код в GitHub
• пращам имейли, SMS и звъня, пазя контакти (настройка: ⚙ > Phone and email)
• водя календара ти („запиши среща в петък в 10“, „какво имам утре?“) и напомням преди всяка среща
• помагам с изпити („имам изпит по история след 4 дни“ - записвам го и правя план за учене) и помня рождени дни
• следя сметките ти („добави сметка за ток 45 евро до 25.11“, „платих тока“) и пиша фактури (никога не плащам сам)
• водя бюджета ти („похарчих 30 евро за храна“, „бюджет за храна 400 евро“, „как съм с бюджета?“)
• следя сделките ти („нова сделка с Acme: сайт 5000 евро“, „Acme е на оферта“, „спечелихме Acme“)
• напомням и повтарям задачи по график („напомни ми утре в 9…“, „всеки ден в 8…“)
• отварям програми, следя процеси, проверявам сигурността на компютъра
• помня какво ми кажеш („запомни, че…“) и уча нови умения
Натисни ☰ горе вдясно за пълното меню, ⚙ за настройките, ❏ за предишните разговори."""
HELP_EN = """I can:
• answer with live data: stocks, crypto, exchange rates, weather, Wikipedia, papers, books, news
• work with files: find, read, write, move, delete (with approval and undo)
• search and download from the web (every link and file is checked for malware)
• write and check code, research code on GitHub
• send email, SMS and make calls, keep contacts (set up: ⚙ > Phone and email)
• keep your calendar ("put the dentist on Friday at 10", "what do I have tomorrow?") and remind you before each appointment
• help with exams ("I have a history exam in 4 days" - saved, then a study plan) and remember birthdays
• track your bills ("add a bill: internet 25 EUR due 30.11", "I paid the electricity") and write invoices (I never pay anything myself)
• keep your budget ("spent 30 EUR on groceries", "set a budget of 400 EUR for groceries", "how is my budget?")
• track your deals ("new deal with Acme: website 5000 EUR", "move Acme to proposal", "we won Acme")
• remind you and repeat tasks on a schedule ("remind me tomorrow at 9...", "every day at 8...")
• open apps, watch processes, audit this PC's security
• remember what you tell me ("remember that...") and learn new skills
Press ☰ (top right) for the full menu, ⚙ for settings, ❏ for earlier conversations."""


# "what do I have tomorrow?", "what's on my calendar", "какво имам утре", "покажи ми програмата за седмицата"
AGENDA_RX = re.compile(r"(?i)^\s*(?:what(?:'s| is)(?: on)? my (?:calendar|agenda|schedule)|what(?: do| have)? i (?:have|got)(?: on| planned)?"
                       r"|(?:show|read)(?: me)? my (?:calendar|agenda|schedule)|my (?:calendar|agenda|schedule)|do i have anything"
                       r"|какво (?:имам|ми предстои)|какъв ми е (?:графикът|графика)|каква ми е програмата"
                       r"|покажи(?: ми)? (?:календара|графика|програмата)|имам ли (?:нещо|ангажименти|срещи))\b(.*)$")
PERIOD_RX = re.compile(r"(?i)today|tomorrow|tonight|week|month|днес|утре|довечера|седмица|месец|календар|calendar|agenda|"
                       r"schedule|програма|график|понеделник|вторник|сряда|четвъртък|петък|събота|неделя|monday|tuesday|"
                       r"wednesday|thursday|friday|saturday|sunday|\d")
CAL_ADD_RX = re.compile(r"(?is)^\s*(?:please\s+|моля\s+)?(?:add|put|schedule|book|запиши|добави|сложи|насрочи)(?:\s+ми)?\s+(.*)$")
CAL_WORDS = re.compile(r"(?i)календар|среща|срещата|час при|час за|рожден ден|ангажимент|събитие|appointment|meeting|"
                       r"calendar|event|birthday|interview|интервю")


def _calendar(request: str, bg: bool) -> str | None:
    from . import agenda

    m = AGENDA_RX.match(request)
    if m and (PERIOD_RX.search(m.group(1) or "") or re.search(r"(?i)calendar|agenda|schedule|програм|график|календар", request)):
        frm, to = agenda.span(m.group(1) or "")
        return _shows(agenda.agenda_text(frm, to, bg, ids=False), [e for _, e in agenda.between(frm, to)])
    m = CAL_ADD_RX.match(request)
    if m and CAL_WORDS.search(request):
        from . import reminders
        from .tools import planner

        ts, rest = reminders.parse_when(m.group(1))
        if ts is None:
            return None  # no clear time: the model asks
        title = re.sub(r"(?i)\b(?:in(?:to)?|to|on) (?:my |the )?calendar\b|в календара|на календара", "", rest)
        title = re.sub(r"(?i)^(?:an?|the|една?|едно)\s+", "", title.strip(" ,.:;-")).strip(" ,.:;-")
        title = re.sub(r"(?i)(?:\s+(?:на|on|at|в|във|for|за|от|from))+$", "", title).strip(" ,.:;-")  # "... на" left by the date
        if len(title) < 2:
            return None
        try:
            ev, clashes = planner.schedule(title[:1].upper() + title[1:], m.group(1))
        except ValueError as e:
            return (f"Не го записах: {e}" if bg else f"Not saved: {e}")
        head = "Записах в календара: " if bg else "Added to your calendar: "
        return head + planner.describe_event(ev, bg) + "." + planner.clash_note(clashes, bg)
    return None


# ---------------------------------------------------------------- bills and invoices (vaelon/bills.py)
_PLEASE = r"^\s*(?:please\s+|моля(?:\s+те)?,?\s+)?"
BILLS_LIST_RX = re.compile(r"(?i)" + _PLEASE + r"(?:(?:what|which|show(?: me)?|list|read(?: me)?)\s+(?:are\s+)?(?:my\s+)?"
                           r"(?:unpaid\s+|open\s+)?bills|(?:my|unpaid|open)\s+bills|bills\s+(?:to pay|due|i (?:have|need|must) to pay)"
                           r"|do i have (?:any )?(?:unpaid |open )?bills|what do i (?:have|need) to pay"
                           r"|какви сметки|кои сметки|неплатени(?:те)? сметки|сметките ми|покажи(?: ми)? сметките"
                           r"|имам ли (?:неплатени |още )?сметки|какво (?:имам да|трябва да|ми остава да) плащам)(?![\w])")
OWED_RX = re.compile(r"(?i)" + _PLEASE + r"(?:who owes me|who (?:hasn't|has not|didn't|did not) pay|unpaid invoices"
                     r"|(?:show|list)(?: me)? (?:my )?(?:unpaid |open )?invoices|кой ми дължи|кой (?:още )?не ми е платил"
                     r"|неплатени(?:те)? фактури|кои фактури (?:не са платени|чакат)|покажи(?: ми)? (?:неплатените )?фактурите)(?![\w])")
PAID_RX = re.compile(r"(?is)" + _PLEASE + r"(?:i(?:'ve| have)? (?:just |already )?paid|i payed|mark|платих|току-що платих|"
                     r"вече платих|отбележи(?: като платена)?)\s+(.{2,80}?)(?:\s+(?:as\s+)?paid|\s+като платена)?\s*[.!]?\s*$")
BILL_ADD_RX = re.compile(r"(?is)" + _PLEASE + r"(?:add|put|save|record|track|new|добави|запиши|сложи|въведи|нова)(?:\s+ми)?\s+"
                         r"(?:(?:a|an|the|new|my|една|нова)\s+)?(?:bill|сметка|сметката)\b[\s:,-]*(.*)$")
SPENT_RX = re.compile(r"(?is)" + _PLEASE + r"(?:how much (?:did i|have i|i) (?:pay|paid|spend|spent)|what did i (?:pay|spend)"
                      r"|колко (?:съм |сме )?(?:платил[аи]?|похарчил[аи]?|изхарчил[аи]?|дал[аи]?)"
                      r"|колко (?:ми )?(?:струваха|излязоха|дадох|платих|похарчих|изхарчих))\b(.*)$")
BILL_WORDS = re.compile(r"(?i)сметк|bill")
BANK_RX = re.compile(r"(?i)извлечени|банк|внеси|импорт|statement|bank|import|transactions|движения")
BILL_FILE_RX = re.compile(r"(?i)(?:add|save|record|track|enter|добави|запиши|сложи|въведи|следи)\b.{0,40}(?:bill|invoice|"
                          r"сметк|фактур)|(?:bill|invoice|сметка|фактура)\b.{0,30}(?:to pay|за плащане)")


# A question never changes data ("платих ли тока?" must not mark the bill paid - found by the code review 2026-11-15).
# Every fast answer that WRITES checks this first; reading answers ("how much did I spend?") do not need it.
ASK_RX = re.compile(r"(?i)\?|(?<![\w])ли(?![\w])|^\s*(?:did|do|does|is|are|was|were|have|has|what|how|when|why|which|who|can|"
                    r"could|should|would|shall|дали|какв\w*|как|кога|защо|кой|коя|кое|кои)(?![\w])")


def asks(text: str) -> bool:
    return bool(ASK_RX.search(text))


def _bills(request: str, bg: bool) -> str | None:
    from . import bills as B, company
    from .security import undo

    if BILLS_LIST_RX.match(request):
        company.require("bills.read")
        return _shows(B.unpaid_text(bg, ids=False), B.unpaid())
    if OWED_RX.match(request):
        company.require("invoices.read")
        return B.owed_text(bg, ids=False)
    if asks(request):
        return None  # the model answers questions; nothing is written
    m = BILL_ADD_RX.match(request)
    if m:
        rest = m.group(1)
        due, rest = B.find_date(rest)
        hit = B.find_amount(rest)
        if not hit:
            return None  # no amount: the model asks for it
        amount, cur, rest = hit
        repeat = B.repeat_of(rest)
        rest = re.sub(r"(?i)\b(?:every month|each month|monthly|quarterly|yearly|every year|annually)\b|всеки месец|ежемесечн\w*|"
                      r"месечн\w*|на 3 месеца|тримесечн\w*|всяка година|годишн\w*", "", rest)
        vendor = B._clean_vendor(rest)
        if len(vendor) < 2:
            return None
        before = B.snapshot()
        b = B.add_bill(vendor, amount, cur, due, "", "", "", repeat, 3)
        undo.push(f"add bill {b['vendor']}", lambda: B.restore_all(before))
        tail = ("" if not due else (" Ще ти напомня 3 дни преди срока." if bg else " I will remind you 3 days before it is due."))
        return ("Записах сметка: " if bg else "Bill added: ") + B.bill_line(b, bg, ids=False) + "." + tail
    m = PAID_RX.match(request)
    if m:
        words = m.group(1)
        said = B.find_amount(words)
        if said and B.category_of(words) == "other" and not BILL_WORDS.search(words):
            return None  # "I paid 20 euros for lunch" is not a bill in the list
        hits = B.match(words)
        if said:  # an amount was said: only a bill of exactly that amount ("15 euros for a taxi" never pays a 120 EUR tax)
            hits = [b for b in hits if b["amount"] == said[0] and b["currency"] == said[1]]
        if not hits:
            return None
        before = B.snapshot()
        b, nxt = B.mark_paid(hits[0]["id"])
        undo.push(f"mark {b['vendor']} paid", lambda: B.restore_all(before))
        out = ("Отбелязах като платена: " if bg else "Marked as paid: ") + B.bill_line(b, bg, ids=False) + "."
        if nxt:
            out += (f" Следващата се очаква {B.day_text(B.date.fromisoformat(nxt['due']), True)} (~{B.money(nxt['amount'], nxt['currency'], True)})."
                    if bg else f" The next one is expected {B.day_text(B.date.fromisoformat(nxt['due']), False)} (~{B.money(nxt['amount'], nxt['currency'])}).")
        return out
    return None  # "how much did I spend ..." is answered by _budget (bills + recorded expenses)


# ---------------------------------------------------------------- the budget (vaelon/budget.py)
EXPENSE_RX = re.compile(r"(?is)" + _PLEASE + r"(?:(?:i\s+)?(?:just\s+)?(?:spent|paid|payed|bought)|похарчих|изхарчих|дадох|платих|"
                        r"купих|разход)\b[\s:,-]*(.+)$")
INCOME_RX = re.compile(r"(?is)" + _PLEASE + r"(?:(?:i\s+)?(?:got paid|received|earned|got)|получих|взех|приход|income)\b[\s:,-]*(.+)$")
LIMIT_RX = re.compile(r"(?is)" + _PLEASE + r"(?:(?:set|make|put|сложи|направи|задай)\s+(?:(?:a|my|ми)\s+)?)?(?:monthly\s+|месечен\s+)?"
                      r"(?:budget|limit|бюджет|лимит)\b[\s:,-]*(.+)$|" + _PLEASE + r"limit\s+(.+)$")
REPORT_RX = re.compile(r"(?is)" + _PLEASE + r"(?:как(?:\s+съм|\s+сме|\s+е)?\s+с?\s*бюджета?|как е бюджетът|бюджетът ми|бюджета ми|"
                       r"покажи(?:\s+ми)?\s+бюджета|how(?:'s|\s+is|\s+am\s+i\s+doing\s+with)\s+my\s+budget|(?:show\s+(?:me\s+)?)?my\s+budget|"
                       r"budget\s+report|where\s+does\s+my\s+money\s+go|за какво (?:харча|отиват парите)|колко\s+(?:пари\s+)?ми\s+остава(?:т)?|"
                       r"how\s+much\s+(?:money\s+)?(?:do\s+i\s+have\s+|is\s+|have\s+i\s+got\s+)?left)\b(.*)$")
INCOME_WORDS = re.compile(r"(?i)заплат|хонорар|приход|salary|wage|paycheck|income|refund|възстанов")
NOT_MONEY_IN = re.compile(r"(?i)сметк|фактур|глоб|акт\b|писмо|имейл|съобщени|bill|invoice|fine\b|ticket|letter|e-?mail|message")
YEAR_WORDS = re.compile(r"(?i)year|година|годината|\b20\d\d\b")


def _yesterday(text: str) -> tuple[str, "object"]:
    from datetime import date, timedelta

    m = re.search(r"(?i)(?<![\w])(yesterday|вчера|онзи ден|the day before yesterday)(?![\w])", text)
    if not m:
        return text, None
    days = 2 if m.group(1).lower() in ("онзи ден", "the day before yesterday") else 1
    return (text[:m.start()] + " " + text[m.end():]).strip(), date.today() - timedelta(days=days)


def _spent(rest: str, bg: bool) -> str | None:
    from datetime import date

    from . import bills as B, budget as BU

    cat = BU.category_of(rest)
    if YEAR_WORDS.search(rest):
        frm, to, label = B.period(rest)
    else:
        frm = BU.month_of(rest)
        to, label = B._shift(frm, "monthly"), BU.month_label(frm, bg)
    if cat == "other":
        if YEAR_WORDS.search(rest):
            return B.summary(frm, to, label, bg)
        return BU.report(frm, bg)
    paid = [b for b in B.load()["bills"] if b["status"] == "paid" and b["category"] == cat and b.get("paid_on")
            and frm <= date.fromisoformat(b["paid_on"]) < to]
    spent = [e for e in BU.load()["entries"] if e["kind"] == "expense" and e["category"] == cat
             and frm <= date.fromisoformat(e["date"]) < to]
    t = B.totals(paid + spent)
    name, n = BU.label(cat, bg), len(paid) + len(spent)
    if not n:
        return (f"Нямам записани разходи за {name} за {label}." if bg else f"I have nothing recorded for {name} in {label}.")
    return (f"За {name} през {label} си платил {B.totals_text(t, True)} ({n} " + ("плащане" if n == 1 else "плащания") + ")." if bg
            else f"You paid {B.totals_text(t, False)} for {name} in {label} ({n} " + ("payment" if n == 1 else "payments") + ").")


# Only the plain request itself (+ a period) is answered here: "cash flow vs profit?", "how is my cash flow
# calculated?" or "can I afford a house with a salary of ..." are questions for the model (#42 review).
_CF_PERIOD = (r"(?:\s+(?:for|over|in|during)\s+(?:the\s+)?(?:next\s+|coming\s+)?(?:\d{1,3}\s*(?:days?|weeks?|months?)|"
              r"(?:a|one|two|three|six)\s+(?:weeks?|months?)|week|month|quarter|weeks|months)|"
              r"\s+(?:this|next)\s+(?:week|month|quarter))?")
CASHFLOW_RX = re.compile(r"(?i)" + _PLEASE + r"(?:how(?:'s|\s+is|\s+does|\s+do)\s+(?:my|our|the)\s+cash\s*-?\s*flow"
                         r"(?:\s+look(?:ing)?)?|(?:show|give)\s+(?:me\s+|us\s+)?(?:my|our|the)\s+cash\s*-?\s*flow"
                         r"(?:\s+forecast)?|(?:(?:my|our)\s+)?cash\s*-?\s*flow(?:\s+forecast)?)(" + _CF_PERIOD +
                         r")\s*[?.!]*\s*$")
AFFORD_RX = re.compile(r"(?i)" + _PLEASE + r"(?:can|could)\s+(?:i|we)\s+(?:still\s+)?afford\s+(.+?)\s*[?.!]*\s*$")
_AFFORD_WHEN = re.compile(r"(?i)\b(?:right\s+now|now|today|this\s+(?:week|month|quarter)|next\s+(?:week|month|quarter)|"
                          r"(?:in|within|over)\s+(?:the\s+)?(?:next\s+)?(?:\d{1,3}\s*(?:days?|weeks?|months?)|"
                          r"(?:a|one|two|three)\s+(?:weeks?|months?)|week|month|quarter))\b")
_AFFORD_THING = re.compile(r"(?i)^(?:(?:for|on)\s+)?(?:(?:a|an|the|my|our|new)\s+)?(?:[a-z][a-z'-]*\s*){0,3}$")
_AFFORD_NOT = re.compile(r"(?i)\b(?:salary|earn\w*|income|with|retire\w*|mortgage|loan|invest\w*|if|per|monthly|"
                         r"yearly|a\s+(?:day|week|month|year)|to|when|without|every|each|daily|weekly|annual\w*|years?|"
                         r"in|by|until|till|after|before|debt|credit|lease|tonight|tomorrow|later|"
                         r"jan(?:uary)?|feb(?:ruary)?|march|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
                         r"sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
                         r"(?:mon|tues?|wed(?:nes)?|thu(?:rs)?|fri|satur|sun)(?:day)?s?|weekends?)\b")


def _horizon(text: str, default: int) -> int:
    t = text.lower()
    for rx, mul in ((r"(\d{1,3})\s*days?", 1), (r"(\d{1,3})\s*weeks?", 7), (r"(\d{1,3})\s*months?", 30)):
        m = re.search(rx, t)
        if m:
            return max(7, min(366, int(m.group(1)) * mul))
    words = {"a": 1, "one": 1, "two": 2, "three": 3, "six": 6}
    m = re.search(r"\b(a|one|two|three|six)\s+(weeks?|months?)", t)
    if m:
        return max(7, min(366, words[m.group(1)] * (7 if m.group(2).startswith("week") else 30)))
    if "quarter" in t:
        return 90
    if "week" in t:
        return 7
    if "month" in t:
        return 30
    return default


def _cashflow(request: str, bg: bool) -> str | None:
    """"how does my cash flow look?", "cash flow for the next 60 days", "can I afford 2000 EUR next month?" (#42).
    English phrases only: anything else goes to the model, which answers in the user's language."""
    from . import bills as B, budget as BU, cashflow

    m = CASHFLOW_RX.match(request)
    if m:
        return cashflow.text(cashflow.forecast(_horizon(m.group(1) or "", 90)), bg)
    m = AFFORD_RX.match(request)
    if not m:
        return None
    rest = m.group(1)
    if not B.AMOUNT_RX.search(rest):
        return None  # "can I afford 3 days off?" - only an amount WITH a currency is money
    hit = B.find_amount(rest)
    if not hit:
        return None
    amount, cur, thing = hit
    when = " ".join(w.group(0) for w in _AFFORD_WHEN.finditer(thing))
    thing = _AFFORD_WHEN.sub(" ", thing).strip(" ,")
    if not _AFFORD_THING.match(thing) or _AFFORD_NOT.search(thing):
        return None  # a bigger question (a salary, a loan, retiring ...): the model answers
    v = BU.convert(amount, cur, BU.load()["currency"])
    if v is None:
        return None  # another currency: the model explains
    a = cashflow.afford(v, _horizon(when, 30))
    f = a["forecast"]
    if not a["known"]:
        return ("To answer that I need the money you have now - say \"my balance is 2000 EUR\" (or set it in Money > "
                "Cash flow).\n" + cashflow.text(f, bg))
    money = B.money(a["lowest_after"], f["currency"], False)
    head = (f"Yes - after spending it, your lowest balance in the next {f['days']} days would be {money}." if a["ok"]
            else f"Not safely - after spending it, your balance would drop to {money} in the next {f['days']} days.")
    return head + "\n" + cashflow.text(f, bg)


def _budget(request: str, bg: bool) -> str | None:
    from . import bills as B, budget as BU
    from .security import undo

    from . import company

    m = SPENT_RX.match(request)
    if m:
        company.require("budget.read")
        return _spent(m.group(1) or "", bg)
    m = REPORT_RX.match(request)
    if m:
        company.require("budget.read")
        rest = m.group(1) or ""
        cat = BU.category_of(rest)
        return BU.report(BU.month_of(rest), bg, "" if cat == "other" else cat)
    if asks(request):
        return None  # "похарчих ли 50 евро?" is a question, not an expense
    m = LIMIT_RX.match(request)
    if m:
        rest = m.group(1) or m.group(2) or ""
        hit = B.AMOUNT_RX.search(rest) and B.find_amount(rest)
        if not hit:
            return None
        amount, cur, rest = hit
        rest = re.sub(r"(?i)\b(?:per|a|each|every|на|всеки|за)\s+(?:month|месец)\b|\bmonthly\b|месечно|\b(?:of|to|от|до|на)\s*$", "", rest)
        cat = BU.category_of(rest)
        cat = "total" if cat == "other" and not re.search(r"[a-zа-я]{3,}", re.sub(r"(?i)\b(?:for|on|за|of|the|my|ми|до|to)\b", "", rest)) else cat
        if cat == "other":
            return None
        v = BU.convert(amount, cur, BU.load()["currency"])
        if v is None:
            return None
        before = BU.snapshot()
        BU.set_limit(cat, v)
        undo.push("set limit", lambda: BU.restore_all(before))
        money = B.money(v, BU.load()["currency"], bg)
        name = BU.label(cat, bg)
        if cat == "total":
            return (f"Общ месечен лимит за разходите: {money}." if bg else f"Overall monthly spending limit: {money}.")
        return (f"Месечен лимит за {name}: {money}." if bg else f"Monthly limit for {name}: {money}.")
    for rx, kind in ((INCOME_RX, "income"), (EXPENSE_RX, "expense")):
        m = rx.match(request)
        if not m:
            continue
        rest, on = _yesterday(m.group(1))
        if not on:
            on, rest = B.find_date(rest)
        if not B.AMOUNT_RX.search(rest):
            return None  # "I spent 3 hours ..." - only an amount with a currency is money
        amount, cur, note = B.find_amount(rest)
        note = re.sub(r"(?i)^(?:за|for|on|от|from|in)\s+|\s+(?:за|for|on|от|from|in)$", "", note.strip(" ,.:;-")).strip(" ,.:;-")
        note = re.sub(r"(?i)^(?:a|an|the|some|my)\s+", "", note)
        if kind == "income" and rx is INCOME_RX and not INCOME_WORDS.search(m.group(1)) and not re.search(r"(?i)got paid|received|получих|earned", request):
            return None
        if kind == "income" and NOT_MONEY_IN.search(m.group(1)):
            return None  # "получих сметка за ток 45 евро" is a bill that arrived, not money that came in
        before = BU.snapshot()
        e = BU.add(kind, amount, cur, "", note, on)
        undo.push(f"add {kind}", lambda: BU.restore_all(before))
        name = BU.label(e["category"], bg)
        money = B.money(e["amount"], e["currency"], bg)
        if kind == "income":
            return (f"Записах приход: {money}" + (f" ({note})" if note else "") + "." if bg
                    else f"Income recorded: {money}" + (f" ({note})" if note else "") + ".")
        return ((f"Записах разход: {money} за {name}" if bg else f"Expense recorded: {money} for {name}")
                + (f" ({note})" if note and note.lower() != name.lower() else "") + "." + BU.warning(e["category"], bg, on=e.get("date")))
    return None


# ---------------------------------------------------------------- deals (vaelon/deals.py)
DEAL_ADD_RX = re.compile(r"(?is)" + _PLEASE + r"(?:new|add|record|track|log|добави|запиши|нова|нов)\s+(?:a\s+)?"
                         r"(?:deal|opportunity|сделка|сделката)\b\s*(?:with|for|със|с|за|:|-)?\s*(.+)$")
DEALS_LIST_RX = re.compile(r"(?i)" + _PLEASE + r"(?:(?:show|list)(?:\s+me)?\s+(?:my\s+|the\s+)?(?:deals|pipeline)|my\s+(?:deals|pipeline)"
                           r"|(?:the\s+)?(?:sales\s+)?pipeline|how\s+are\s+(?:my\s+|the\s+)?deals(?:\s+going)?|deals\s+report"
                           r"|сделките\s+ми|покажи(?:\s+ми)?\s+сделките|как\s+вървят\s+(?:сделките|продажбите)|какви\s+сделки\s+имам"
                           r"|кои\s+сделки)(?![\w])")
FOLLOW_RX = re.compile(r"(?is)" + _PLEASE + r"(?:follow[ -]up\s+(?:with|on)|check\s+back\s+with|проследи(?:\s+сделката\s+с)?"
                       r"|свържи\s+се\s+отново\s+с|следваща\s+стъпка\s+(?:за|с))\s+(.+)$")
QUESTION_RX = ASK_RX
CAL_TALK = re.compile(r"(?i)meeting|среща|срещата|\bcall\b|обаждане|обади|cancel|отмени|reschedul|calendar|календар|lunch|обяд")
# a stage changes only from a plain statement about the deal (the review found "Ivan will lead the Acme project" -> lead)
_STAGE_SAY = [
    (re.compile(r"(?is)^\s*(?:please\s+|моля\s+)?(?:move|mark|set|put|премести|отбележи|сложи)\s+(?:the\s+)?(?:deal\s+(?:with\s+)?|"
                r"сделката\s+(?:с\s+|със\s+)?)?(.+?)\s+(?:to|as|on|in|into|на|като|в|във)\s+(.+?)\s*[.!]?$"), "move", True),
    (re.compile(r"(?is)^\s*(?:we\s+)?(?:have\s+|just\s+)?(won|lost|спечелихме|загубихме)\s+(?:the\s+)?(?:deal\s+with\s+|"
                r"сделката\s+(?:с\s+|със\s+)?)?(.+?)(?:\s+deal)?\s*[.!]?$"), "verb_first", True),
    (re.compile(r"(?is)^\s*(?:the\s+)?(?:deal\s+with\s+|сделката\s+(?:с\s+|със\s+)?)?(.+?)\s+(?:is|е|stays|остава)\s+(?:now\s+|вече\s+)?"
                r"(?:in\s+|at\s+|on\s+|на\s+|в\s+|във\s+)?(.+?)\s*[.!]?$"), "is", False),
    (re.compile(r"(?is)^\s*(.+?)\s+(signed(?:\s+the\s+contract)?|said\s+no|declined|rejected|accepted\s+the\s+offer|"
                r"подписа\w*(?:\s+договора)?|отказа\w*|приеха\s+офертата)\s*[.!]?$"), "verb_after", False),
]


def _stage_said(text: str):
    """(who, stage, explicit) from a plain statement about a deal's stage, or None."""
    from . import deals as D

    for rx, kind, explicit in _STAGE_SAY:
        m = rx.match(text)
        if not m:
            continue
        if kind == "verb_first":
            return m.group(2).strip(" ,.:;-"), D.stage_of(m.group(1)), explicit
        st = D.stage_of(m.group(2))
        if st:
            return m.group(1).strip(" ,.:;-"), st, explicit
    return None


def _deals(request: str, bg: bool) -> str | None:
    from . import bills as B, deals as D
    from .security import undo

    if DEALS_LIST_RX.match(request):
        from . import company

        company.require("deals.read")
        return D.pipeline_text(bg, ids=False)
    if asks(request):
        return None
    m = DEAL_ADD_RX.match(request)
    if m:
        rest = m.group(1)
        hit = B.AMOUNT_RX.search(rest) and B.find_amount(rest)
        value, cur = (hit[0], hit[1]) if hit else (0, "EUR")
        if hit:
            rest = hit[2]
        parts = re.split(r"\s*(?::|\s-\s|\s–\s|\bза\b|\bfor\b|\babout\b|\bотносно\b)\s*", rest, maxsplit=1)
        client = re.sub(r"(?i)^(?:with|със|с)\s+", "", parts[0]).strip(" ,.:;-")
        title = re.sub(r"(?i)^(?:a|an|the)\s+", "", parts[1].strip(" ,.:;-")) if len(parts) > 1 else ""
        if len(client) < 2:
            return None
        before = D.snapshot()
        d = D.add(client[:1].upper() + client[1:], title, value, cur)
        undo.push(f"add deal {d['client']}", lambda: D.restore_all(before))
        return ("Записах сделка: " if bg else "Deal recorded: ") + D.deal_line(d, bg, ids=False) + "."
    m = FOLLOW_RX.match(request)
    if m:
        from datetime import datetime as _dt

        from . import reminders

        words = m.group(1)
        hits = [d for d in D.match(words, open_only=True) if d["client"].lower() in words.lower()]
        if not hits:
            return None
        ts, rest = reminders.parse_when(words)
        if ts is None:
            return None
        d = hits[0]
        step = re.sub(r"(?i)" + re.escape(d["client"]), "", rest)
        step = re.sub(r"(?i)^(?:about|re|за|относно|:|-|\s)+|(?:\s+(?:on|at|в|на))+$", "", step.strip(" ,.:;-")).strip(" ,.:;-")
        step = re.sub(r"(?i)^(?:the|a|an)\s+", "", step)
        when = B.day_text(_dt.fromtimestamp(ts).date(), bg)
        if when not in ("днес", "утре", "today", "tomorrow"):
            when = ("на " if bg else "on ") + when
        before = D.snapshot()
        d = D.update(d["id"], next_step=step or ("свържи се отново" if bg else "follow up"),
                     next_date=_dt.fromtimestamp(ts).date().isoformat())
        undo.push(f"follow up {d['client']}", lambda: D.restore_all(before))
        return (("Ще ти напомня " if bg else "I will remind you ") + when
                + ": " + D.deal_line(d, bg, ids=False) + ".")
    if len(request) > 140 or asks(request) or CAL_TALK.search(request):
        return None  # "cancel the meeting with Acme" is about the calendar, not the deal
    said = _stage_said(request)
    if not said:
        return None
    who, st, explicit = said
    hits = [d for d in D.match(who) if d["client"].lower() in who.lower() or who.lower() in d["client"].lower()]
    if not hits or not st:
        return None  # no deal named: maybe it is about something else
    d = hits[0]
    order = list(D.STAGES)
    if not explicit and st in D.OPEN and d["stage"] in D.OPEN and order.index(st) < order.index(d["stage"]):
        return None  # never a step back unless said plainly ("move Acme to lead")
    if d["stage"] == st:
        return ("Вече е отбелязана така: " if bg else "It is already marked so: ") + D.deal_line(d, bg, ids=False) + "."
    before = D.snapshot()
    d = D.update(d["id"], stage=st)
    undo.push(f"deal {d['client']} {st}", lambda: D.restore_all(before))
    out = ("Отбелязах: " if bg else "Updated: ") + D.deal_line(d, bg, ids=False) + "."
    if st == "won" and d["value"]:
        out += (" Да направя ли фактура? Кажи „направи фактура за сделката с " + d["client"] + "“." if bg
                else f" Want the invoice? Say \"make the invoice for the {d['client']} deal\".")
    return out


def _remember(request: str, bg: bool, memory) -> str | None:
    m = REMEMBER_RX.match(request)
    if not m or memory is None or asks(request):  # "remember my wife's name?" is a question, not a fact
        return None
    fact = m.group(1).strip()
    memory.add(fact, kind="user")
    profile.observe(fact)
    return f"Запомних: {fact}" if bg else f"Noted: {fact}"


def _about_me(request: str, bg: bool, memory) -> str | None:
    if not ABOUT_ME_RX.search(request):
        return None
    summary = profile.summary(lang="bg" if bg else "en")
    user_facts = [t for _, t in (memory.recent(8, kind="user") if memory else [])]
    if not summary and not user_facts:
        return ("Още не знам нищо за теб. Кажи ми, например: „Казвам се …, живея в …“ или „запомни, че …“." if bg
                else "I don't know anything about you yet. Tell me, e.g. \"My name is ..., I live in ...\" or \"remember that ...\".")
    out = ["Ето какво знам:" if bg else "Here is what I know:"]
    if summary:
        out.append("• " + summary)
    out += [f"• {t}" for t in user_facts]
    return "\n".join(out)


COMPARE_RX = re.compile(r"(?i)\b(compare|comparison|versus|vs\.?|difference between|which is (better|warmer|colder|cheaper))\b"
                        r"|сравни|сравнение|разлика(та)? между|по-(добр|топл|студен|евтин)")


DEMO_RX = re.compile(r"(?i)^\s*(?:please\s+|моля\s+)?(?:зареди|добави|сложи|махни|изтрий|премахни|load|add|remove|delete|clear)"
                     r"\s+(?:the\s+|some\s+)?(?:демо\s+данн\w*|демо(?:то)?|demo\s+data|the\s+demo|demo)\s*[.!]?\s*$")


def detect(request: str, memory=None, on_event=None, work_only: bool = False) -> Hit | None:
    """Return a Hit for clear requests, None to let the agent loop handle it. Network errors fall through."""
    text = request.strip()
    if not text or len(text) > 240:
        return None
    bg = is_bg(text)
    m = DEMO_RX.match(text)
    if m:
        from . import demo

        try:
            if re.search(r"(?i)махни|изтрий|премахни|remove|delete|clear", text):
                return Hit(answer=demo.text(demo.remove(), False, bg))
            return Hit(answer=demo.text(demo.load(), True, bg))
        except PermissionError as e:  # company mode: only the owner loads or removes demo data
            return Hit(answer=(f"Не мога: {e}." if bg else f"I can't: {e}."))
        except ValueError:
            return Hit(answer=("Демо данните вече са заредени. „Махни демо данните“ ги маха." if bg
                               else "The demo data is already there. \"Remove the demo data\" takes it away."))
    if HELP_RX.match(text):
        return Hit(answer=HELP_BG if bg else HELP_EN)
    from .company import Denied

    try:
        ans = None if work_only else (_remember(text, bg, memory) or _about_me(text, bg, memory))
        if not ans and not work_only:
            from . import reminders

            ans = reminders.from_request(text, bg)  # "remind me in 10 minutes to ..." - the time is read by code
        if not ans:
            ans = _cashflow(text, bg)  # "how does my cash flow look?", "can I afford 2000 EUR next month?"
        if not ans:
            ans = _bills(text, bg)  # "платих тока", "what bills do I have", "добави сметка за ток 45 лв до 25.11"
        if not ans:
            ans = _budget(text, bg)  # "похарчих 30 лв за храна", "бюджет за храна 400 евро", "как съм с бюджета?"
        if not ans and not work_only:
            from . import life

            ans = life.answer(text, bg)  # "имам изпит след 3 дни" -> calendar + study plan; birthdays, anniversaries
        if not ans and not work_only:
            ans = _calendar(text, bg)  # "what do I have tomorrow?", "запиши среща в петък в 10"
        if not ans:
            ans = _deals(text, bg)  # "нова сделка с Acme: сайт 5000 евро", "спечелихме Acme", "как вървят сделките?"
    except Denied as e:
        return Hit(answer=(f"Не мога: {e}." if bg else f"I can't: {e}."))
    except Exception:
        ans = None
    if ans:
        return Hit(answer=ans, outside=isinstance(ans, _Outside))

    from .tools import knowledge as K

    def emit(name):
        if on_event:
            on_event("tool", name)

    steps = []
    if STOCK_RX.search(text):
        steps.append(("stock_quote", _stock))
    if WEATHER_RX.search(text):
        steps.append(("weather", lambda r, b, k: _weather(r, b, k, work_only)))
    steps += [("crypto_price", _crypto), ("exchange_rate", _fx)]
    if COMPARE_RX.search(text):
        steps = []  # "compare A and B" needs several lookups and a judgement: that is the model's job
    for name, fn in steps:
        try:
            if name == "crypto_price" and not any(re.search(r"(?<!\w)" + re.escape(w), text.lower()) for w in COINS):
                continue
            if name == "exchange_rate" and not _currencies(text):
                continue
            emit(name)
            ans = fn(text, bg, K)
        except Exception:
            ans = None
        if ans:
            return Hit(answer=ans)
    m = WIKI_RX.match(text)
    if m and not WIKI_SKIP.search(m.group(1)):
        return Hit(tool="wiki", args={"topic": m.group(1).strip(" ?.!"), "lang": "bg" if bg else "en"})
    return None
