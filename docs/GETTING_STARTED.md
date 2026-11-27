# Getting started

## 1. Install the app

**Windows 10 / 11**
1. Download `Vaelon-Setup-<version>.exe` from the release page and run it. Windows asks once for administrator rights:
   Vaelon goes into Program Files, where no other program can change it.
2. If SmartScreen says "Windows protected your PC", click **More info** > **Run anyway** - the app is not code-signed
   (that needs a paid certificate).
3. Start Vaelon from the Start menu (or the desktop shortcut, if you chose one).

**macOS 14 or later, Apple silicon (M1 or newer)**
1. Download `Vaelon-<version>.dmg` from the release page, open it and drag **Vaelon** onto **Applications**.
2. Open Vaelon from Applications. The first time macOS says it cannot check the app: open **System Settings >
   Privacy & Security**, scroll down, click **Open Anyway** and confirm. This happens once - the app is signed ad hoc,
   not notarised (that needs a paid Apple account). On recent macOS a right-click > Open is no longer enough.
3. When you first use the microphone, macOS asks for permission. Changed your mind later: System Settings > Privacy &
   Security > **Microphone** > Vaelon. The same place has **Screen Recording**, used only while the eye is on.

Your data lives in `.vaelon` in your home folder (`%USERPROFILE%\.vaelon` / `~/.vaelon`). Updating or uninstalling
never removes it, nor the files Vaelon made for you (`Documents/Vaelon`). Uninstall: Windows Settings > Apps >
Vaelon; on a Mac drag Vaelon from Applications to the Bin.

## 2. The first start: where Vaelon thinks

A short setup opens. Every step can be skipped and changed later in Settings; one choice matters:

- **On this computer** - private, nothing leaves it; the speed depends on the computer (an Apple-silicon Mac is fast).
  1. Click **Get Ollama** (it opens https://ollama.com/download), install it and start it.
  2. Back in the setup, Vaelon looks at this computer (memory, processor, graphics) and lists a few models: what each
     is good for, its download size, how much memory it needs, whether it fits and how fast it will feel. One is marked
     **Recommended for this computer**. Press **Download the model** on it (a bar shows the progress); a model you
     already have only needs **Use this model**. Prefer a terminal? `ollama pull <model>` does the same.
  3. The setup says by itself when the model is ready.
- **In the cloud** - faster, but your text goes to that company. Get a free key (Groq: https://console.groq.com/keys,
  Gemini: https://aistudio.google.com/apikey) and paste it into the key box of the setup or of Settings. Never paste a
  key into the chat.

Without a model Vaelon still answers simple things at once (time, weather, prices, *"what is on my calendar"*,
*"what bills do I have"*), but conversations, files, documents and research need one.

Then: ☰ shows everything Vaelon can do, with examples, and **?** (or `/help`) opens the Help page - every part
explained, plus Feedback. Vaelon answers in the language you write in. Optional: Settings > **Profiles** (Business,
Learning, Coding, Creator, Everyday life).

**Voice:** the installed app speaks with your computer's own voice. For a missing language add one in Windows Settings >
Time & language > Speech, or on a Mac in System Settings > Accessibility > Spoken Content > System voice > Manage voices.
The private neural voices (Piper) are added with `vaelon voice-setup` when Vaelon is installed from source.

## 3. From source (developers, any system)
1. Install **Python 3.10+**, **Ollama** and, to build the interface, **Node 20+**.
2. From the project folder:
   ```
   pip install -e ".[all]"
   vaelon voice-setup
   vaelon doctor
   ollama pull qwen3:4b-instruct
   ```
3. Start it: `vaelon app` (desktop window) or `vaelon chat` (terminal). Build the apps yourself: see the README.

## Faster and smarter (optional, free keys)
In the app: Settings > the key box. In a terminal (source install):
```
vaelon key set            # pick GROQ_API_KEY from the list, paste the key at the hidden prompt
vaelon provider groq
```
Get a key at https://console.groq.com/keys (or Gemini: https://aistudio.google.com/apikey). Keys are stored
encrypted in the vault. Never type a key on the command line or in the chat - only at the hidden prompt.
A cloud model sees your messages. Back to fully local: `vaelon provider local`.

Stock prices work without a key (Yahoo Finance, unofficial). For an official source add a free key:
`vaelon key set TWELVEDATA_API_KEY` (https://twelvedata.com/pricing - quotes and history) and/or
`vaelon key set FINNHUB_API_KEY` (https://finnhub.io/register - real-time US quotes). Vaelon uses the best one
it has and falls back by itself; every answer names its source.

Free tiers have per-minute limits (Groq: about 8,000 tokens per minute per model). When one model is busy, Vaelon
switches to another model of the same provider, and finally to your local model, by itself.

## How fast is it?
Type `/speed`. After every answer a line shows the seconds from the moment you finished to: your words as text,
the first words of the answer, the first sound of the voice. Type `/speed` again to turn it off.

## Voice
The ◉ button (or `/voice`) opens the Voice Designer: presets Vaelon, Butler, Titan, Machine, Radio, Ghost, Clean and
sliders. Studio-quality cloud voice: `vaelon key set` (pick ELEVENLABS_API_KEY) and
`vaelon config tts_engine elevenlabs`. Vaelon caps its own ElevenLabs use at `elevenlabs_monthly_chars` (8,000 by
default) and then switches to the free local voice. It streams: you hear a sentence while ElevenLabs is still
making it, and a sentence it already said is replayed from memory without using credits.

## Phone, email, Telegram (optional)
Open Settings (⚙) > **Phone and email** - everything is stored encrypted, never in the chat:
- Email: pick your provider (Gmail, Outlook, iCloud, Yahoo), enter your address and an **app password** (Gmail and
  Outlook: turn on 2-step verification, then create an app password - never use your normal password).
- Calls and SMS: a Twilio account (twilio.com) gives you the account SID, the auth token and a phone number.
  A trial account can only call and text numbers you verified there.
- Contacts: just say "save Mum's number +15550100123". They are kept encrypted (`contacts.enc`).
- Telegram: `VAELON_TELEGRAM_TOKEN` from @BotFather (Settings > keys), then `vaelon telegram`.
Vaelon shows you every email, SMS and call before it goes and waits for your yes.

If you edit the code yourself: `vaelon integrity sign`. If something breaks: `vaelon doctor`.
Not yet tested against the real services: Twilio, Telegram, the microphone wake word, the vision model.

## Several tasks at once
Type a second request while the first is still working - it starts immediately. The swarm splits into one coloured
cluster per task (up to four). Click a task's label to see what it is doing step by step, or to cancel it.
Type `/stop` to cancel everything.

## The companion (hands-free)
Press **hands-free** next to the microphone (or type `/talk`). A small window that stays on top appears - drag it
wherever you like and just talk. Vaelon answers aloud; talk over it to interrupt, say "stop" to cancel.
- The **eye** button lets it see your screen: ask "what does this error say?" and it looks first.
- The **arrows** button brings the full window back.
- The **bolt** button turns on Live voice: faster, real-time, can be interrupted at any moment. It needs a
  Gemini key (`vaelon key set GEMINI_API_KEY`) and sends your microphone audio to Google while it is on.
If the small window says "Click to start talking", click it once (Windows unlocks sound only after a click).
Headphones give the best result; with loudspeakers keep the volume moderate.

## Settings and keys in the app
Press the gear button. Paste a key into its box and press Save: it is sealed in the encrypted vault and never shown
again. Then pick the provider card. The first time you start Vaelon, a short setup asks the same things.

## Calendar
Press the calendar button or say "add a meeting on Friday at 10" / "what do I have tomorrow?". Vaelon reminds you before each appointment.
"Export .ics" gives you a file for Google Calendar or Outlook; "import this .ics" (attach the file) brings theirs in.

## Bills and invoices
Open Money or say "add a bill: electricity 45 EUR due 25.11" / "what bills do I have to pay?". Vaelon reminds you before
each due date and never pays anything itself: after you pay, say "I paid the electricity bill" or press Paid. Attach a bill's PDF or
photo and say "add this bill". Fill in "My business" once, then make invoices in the panel or by saying "make an
invoice for Acme Ltd: Web design | 1 | 500".

## Budget
Open Money > Budget or just say what you spent: "spent 30 EUR on groceries", "spent 12 EUR on coffee". Set a
limit: "set a budget of 400 EUR for groceries". Ask "how is my budget?" any time. Paid bills are counted by themselves.

## Cash flow
Money > Cash flow: type the money you have now, pick 30, 60 or 90 days and see each week's money in, money out and
balance, with a warning when it may run short. Or ask "how does my cash flow look?" or "can I afford 2000 EUR next
month?".

## Quotes
Money > Quotes: fill in the client and the lines and press **Make the quote** (or say "make a quote for Acme: 10 hours
of design at 60 EUR"). Mark it sent; when the client says yes, **Accepted** makes the invoice with the same lines.

## Deals
Money > Deals: add a deal ("new deal with Acme: website 5000 EUR"), move it along ("move Acme to proposal"), set the
next step ("follow up with Acme on Friday") and Vaelon reminds you that day. "We won the Acme deal" marks it won; the
Invoice button makes its invoice.

## Bank statements, exams, birthdays
Money > Budget > Import bank CSV: the statement from your online banking goes into the budget (preview first).
"I have an exam in 3 days" saves the exam and offers a study plan. "Mum's birthday is on 12 March" is remembered
every year. "Load demo data" fills everything with made-up entries to try it; "remove the demo data" removes them.

## Company mode (optional)
Money > Company > Turn on: your name and a PIN. Add a company, add people with a role and a PIN, tick which companies
each may open. "Lock" hands Vaelon over; the next person signs in with their PIN. The journal shows who changed what.

## Conversations
The ❏ button lists your conversations. `/new` starts a fresh one; the old ones stay in the list.

## Better web search (optional)
Without a key Vaelon searches through public engines, which sometimes refuse automatic requests. For a dependable
search add a free key in Settings: `TAVILY_API_KEY` (https://app.tavily.com) or `BRAVE_SEARCH_API_KEY`
(https://api-dashboard.search.brave.com).

## Outside tools (MCP)
Thousands of ready-made tool servers follow the MCP standard. Add one in a terminal - Vaelon shows what it will run
and which tools it brings, and asks you to confirm:
```
vaelon mcp add files -- npx -y @modelcontextprotocol/server-filesystem C:\Users\you\Documents
```
Restart Vaelon, then say "use files to ...". Vaelon asks before every call; `vaelon mcp list` shows what is connected.
A local server is a program running on your PC with your rights - add only ones you trust.

## About and license
`/about` (or `vaelon about`) shows the version, the author and the license. Vaelon is free software under
GPL-3.0-or-later: you may share and change it, but every copy must stay open source and keep the author credit.

## Make files
Say what you want as a file: "save it as PDF", "make an Excel table", "create a presentation", "make a podcast".
The file appears as a card under the answer with **Open** and **Show in folder** (audio also has **Play**).
All files are in `Documents/Vaelon`.

## Deep research
Type `/research` and a topic. In about 20 seconds you get a report with numbered sources, also saved as a Word file.

## Reminders
"Remind me in 20 minutes to ..." or "Remind me tomorrow at 9 to ...". You get a system notification and a line in
the app. "Every day at 08:00 ..." repeats a request on its own.

## Attach a picture or a document
Press the paperclip (or paste / drop a file) and ask your question. With a cloud model the file content is sent to
that provider; with the local model it stays on your PC.
