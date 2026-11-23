# Changelog

## Unreleased
### Added
- **Download the model from the app**: when Ollama runs but the local model is missing, the first-run setup and
  Settings have a **Download the model** button with a progress bar - no terminal needed. Vaelon asks the
  user's own Ollama to download the model it is set to use, or one from Vaelon's list, one download at a time.
- **Choose the local model**: Settings and the first-run setup list a few models (light, balanced, with pictures,
  stronger, most capable) with what each is good for, its size and memory need, whether it fits this computer and
  how fast it will feel - Vaelon reads the memory, processor and graphics of the computer (never sent anywhere)
  and recommends one. Download and switch in place; only models from that list can be downloaded.
### Fixed
- Quick answers (bills, calendar, budget, bank import) show their lines as a real list; a calendar day
  heading no longer glues onto the previous day's last event.

## 0.18.0 - 2026-11-18
### Changed
- **A new interface.** A navigation rail with line icons (conversations, money, calendar, voice, examples, help,
  settings), a slim top bar with the status, a welcome screen with things to try, message bubbles, a new composer,
  calmer panels, sentence-case text and one warm accent colour. The swarm and its animations stay. The previous
  interface (0.17.0) is kept in `versions/0.17.0-classic`.
- **Smaller app: 130 MB instead of 197 MB** (a 41 MB installer). Only parts the app never uses were left out (Hebrew /
  Arabic voice models, unused speech dictionaries, a native C library, web-server and training code); checked with
  the senior reviewer and the white-hat tester, and the voice output was compared phoneme by phoneme with the old
  bundle (identical).
- Examples, hints, help, demo data and documents are neutral (no country-specific numbers, providers or currencies).
### Added
- **macOS.** Vaelon runs on a Mac (macOS 14 or later, Apple silicon). `scripts/build_mac.py` (run on a Mac) builds `Vaelon.app` and a
  drag-to-Applications disk image. No paid Apple account is used: the app is signed ad hoc and not notarised, so the
  first time macOS asks once (System Settings > Privacy & Security > "Open Anyway"). On a Mac the vault's master key
  is sealed with a key kept in the macOS Keychain, notifications use Notification Center, the built-in `say` voice
  stands in when Piper has no voice for a language, and Mac private places (Keychains, cookies, mail, messages, browser
  data, shell history) and auto-start places (LaunchAgents, login shell files, crontab) are protected like their
  Windows counterparts. The release workflow builds both systems.
- **Settings > Look and sound**: switch off the visual glitches, the voice glitches, or the orange dot before
  Vaelon's messages.
- **Get Ollama**: the first-run setup and Settings have a button that opens Ollama's official download page when
  the local model server is not answering; the setup checks again by itself every few seconds.
- **Install and start** on Windows and macOS is explained step by step in the README, Getting Started and Help
  (SmartScreen / Open Anyway, the microphone permission, where the data lives, how to uninstall, the system voice).
- **Installer** (`installer/vaelon.iss`, Inno Setup): installs into Program Files (one administrator prompt, so no other
  program can change Vaelon's files), replaces the whole program folder on update, waits for a running Vaelon, starts
  Vaelon as the normal user, and never touches your data (`~/.vaelon`, `Documents\Vaelon`) on install, update or
  uninstall.
### Security
- The installed app ignores `VAELON_UI_DIR` (another program could otherwise point it at a foreign page that would get
  the access key), refuses to import modules that were left out of the bundle (a file planted under such a name never
  runs), and refuses to run as administrator. `check_secrets.py` refuses certificate and key files.
- **A red-team attack, a white-hat analysis and a senior review (2026-11-18).** What changed:
  - Settings files and folders that run code by themselves now always need your approval before Vaelon writes them:
    any dot-file or dot-folder (`.gitconfig`, `.git/config`, `.zlogin`, `.config/fish`, `.vimrc` ...), app settings
    areas (`AppData`, `~/Library`, except iCloud / cloud-drive folders and Temp) and many more program and shortcut
    types (`.pth`, `.docm`, `.library-ms`, `.terminal` ...). A name ending in a dot or a space is refused on Windows
    (Windows silently drops them: `run.bat.` became `run.bat`).
  - Outside content can no longer be "washed" through the conversation: an answer written after a web page, a file or
    an import is marked, and later turns keep the extra care (addresses nobody gave, your data going out, remembering,
    handing work to a specialist, self-learning). Imported calendar events, bills read from files and bank lines keep
    their origin, so showing them later counts as outside content too. Links that a page or a search really returned
    still open without a card.
  - After Vaelon read your own data (contacts, files, bills ...), sending it to an address nobody gave needs your yes.
  - A scheduled task always needs your approval (it runs later with nobody watching). The approval card for writing a
    file shows what will be written; the card for code shows the task.
  - Downloads and attachments get the "from the internet" mark (Windows Mark of the Web, macOS quarantine), so Office
    opens them in Protected View and Windows / macOS check programs before they run.
  - Commands that touch Vaelon's Keychain item are refused; commands that make something start by itself get a
    warning on the card. The release workflow builds with read-only rights and a fixed Inno Setup version.
### Fixed
- **macOS needs version 14** (the bundled numpy / onnxruntime are built for it) and Apple silicon: the app now says
  so itself (`LSMinimumSystemVersion` 14.0) and every page says the same. After ElevenLabs (cap reached or not
  answering) a Mac falls back to its own voice, like Windows. Feedback notes name the real system.
- Texts no longer send users of the installed app to terminal commands only a source install has.
- **The animation could disappear.** A minimised window (zero size) with two or more tasks running turned every
  particle into an invalid number and the swarm stayed empty until a restart; a lost graphics context (after a driver
  or GPU reset) was never rebuilt; if graphics could not start at all, the whole window went blank. Now a zero size is
  ignored, invalid numbers are repaired, a lost context is rebuilt after 3 seconds and a failed start is retried while
  the rest of the app keeps working. The motion is damped per second instead of per frame, so on a busy computer a
  glitch no longer throws the particles out of view, and the companion's orb stays visible under "Click to start".

## 0.17.0 - 2026-11-16
### Added
- **Profiles (optional)**: Business, Learning, Coding, Creator, Everyday life - pick none, one or several in the
  first-run setup or Settings > Profiles. A profile keeps a few of its tools always ready, tells Vaelon in one line how
  you like to be helped and puts its examples first in the menu. Nothing is switched off and no right is granted.
- **Help page** (the ? button, `/help`): everything explained in one place, with search; the screens keep only short
  hints and a small "?" that opens the right section. `/menu` opens the examples menu.
- **Feedback** (Help > Feedback, `/feedback`): an idea, a problem, a question - saved as a text file you can read
  before sharing (your text, the Vaelon / Windows version and local-or-cloud; no name, keys, files or chats). Nothing
  is sent by itself.
### Security (a full review of every file by five reviewers, then an attack on the running app)
- Another program could take over Vaelon's port on Windows (a second program may bind a port in use) and receive the
  app's key and everything typed. The port is now held exclusively, the app checks that the core proves it knows the
  key before it hands anything over, and the Live voice bridge does the same both ways - the key never crosses it.
- After outside content (a web page, an e-mail, a file) entered a task: opening an address the model made up (a way to
  send your data out), remembering, forgetting, undoing and handing work to a specialist now need your approval; a
  specialist inherits and returns that state; facts learned from the web mark the task the same way.
- Writing a program, script or shortcut, or into a place where files start by themselves (Startup folder, shell
  profile, git hooks), always needs approval. The approval card shows the whole action (nothing blanked but your real
  stored keys) and the folder of a command. "Allow" answers only the card you see (a stale card or a double click
  cannot approve the next action).
- Files: searches can no longer leave the allowed folders or see Vaelon's data; network shares, devices and hidden
  streams are refused before anything touches them; more credential files are protected (git, npm, Docker, browsers,
  PowerShell history ...); big files and pages are read only up to a limit and with a deadline.
- Company mode fails closed (an unreadable company file keeps Vaelon locked), a person can never be left without a
  company (they would have landed in the owner's space), locking or signing in ends Live voice and clears the screen,
  scheduled tasks run as the owner, re-enabling company mode takes the new PIN.
- The audit log can no longer be stopped by a broken line, keeps its chain under parallel tasks and stores what you
  wrote encrypted; scheduled tasks and their results are encrypted too.
### Security (white-hat penetration test, 2026-11-18: three testers + the lead, fixes agreed with the senior reviewer)
- After outside content, a search or lookup that would send YOUR data (memory, profile, a file, mail, money) to an
  outside service asks first - ordinary searches stay silent.
- Approval cards show the action as it is: hidden characters (right-to-left tricks, zero-width, control codes) are
  removed and said so, the end of a long text is always visible, and Vaelon's own remark is shown apart.
- Encrypted files never accept plain text (a forged company file keeps Vaelon locked); planted memory rows are dropped.
- Security settings in config.json (model server, allowed folders, auto-approve ...) changed by anything other than
  Vaelon are not used - the last trusted values are, and Settings shows a red warning (`vaelon config confirm` accepts).
- A code change outside approved updates shows a red warning in the app and a Windows notification; deleting the
  signed list of files no longer resets the trust.
- Some actions (commands, deleting for ever, sending mail / SMS, calls, downloads, extensions, self-changes) can never be
  set to skip the approval card.
- Idle connections are closed after 20 s and at most 64 are served at once; a colleague's attachments are previewed in
  the app, never opened in the owner's Office; attachments get the Mark of the Web (Protected View); CSP tightened;
  the window bridge exposes nothing the page could misuse; saves retry when Windows briefly locks a file.
### Fixed
- Undo never takes an issued invoice back (the numbering stays unbroken); "45,20 lv." is 45.20; bare dates such as
  "20.11 at 15:00" are read; impossible dates ("31.11") are refused; an unreadable reminders or profile file is never
  overwritten; invoice rows never split across pages; phone numbers and IDs stay text in Excel; control characters
  no longer break exports; .ics import converts time zones, skips duplicates and marks repeat rules it cannot follow.
- "What time is my meeting?" is no longer answered with the clock; a JSON example in an answer is no longer run as a
  tool; the ElevenLabs monthly cap holds when many sentences are voiced at once; the companion can no longer open two
  microphones; the newest phrase always wins in hands-free.

## 0.16.0 - 2026-11-15
### Added
- **Company mode** (Money > Company, `/company`, `vaelon company enable`). Off by default - then nothing changes.
  - **Companies**, each with its OWN bills, invoices, business details, budget, deals and journal
    (`~/.vaelon/workspaces/<id>/`); the personal workspace keeps today's files and is the owner's alone.
  - **People with roles and a PIN** (4-8 digits, PBKDF2; five wrong tries lock that person out for a minute):
    owner (everything), accountant (bills, invoices, budget, bank import, export, journal; reads deals), sales (deals;
    reads invoices), member (records expenses and income; reads bills), viewer (reads only).
  - **Lock** button; a locked Vaelon answers nothing but the sign-in. On the owner's PC the owner is signed in at start
    unless "ask for a PIN when Vaelon starts" is ticked.
  - **Work mode** for everyone who is not the owner: their tasks never see the owner's memory, profile,
    conversations, calendar, files, mail or settings - only money and lookup tools, and their own conversation. They see
    only their own tasks; the calendar, conversations, settings and voice designer are hidden from them.
  - **Journal** of who changed what (bills, invoices, budget, deals, people, sign-ins, undo), encrypted and chained
    with an HMAC - a line changed, removed or inserted outside Vaelon is reported.
  - Reminders cover every company, not only the open one.
  - Connected tools (MCP) - e.g. accounting software - only for the owner and the accountant. `docs/ACCOUNTING.md`:
    Xero and QuickBooks Online have MCP servers; other programs export through Excel for now.
- Honest limit, said in the app: on ONE Windows account this protects against mistakes and casual misuse, not against
  someone who can use that Windows account directly. Separate Windows accounts give real separation.

## 0.15.0 - 2026-11-15
### Added
- **Bank statement import** (Money > Budget > Import bank CSV, or attach the CSV and say "import this bank statement"). Reads
  column names in several languages, `;` `,` or tab, UTF-8 or Windows-1251, decimal comma or point; Revolut's
  reverted / declined lines are skipped. A payment that matches an unpaid bill marks the bill paid; an incoming payment
  that matches an invoice marks the invoice paid; the rest becomes budget expenses / income with a guessed category.
  You see a preview first; nothing is imported twice; one Undo takes a whole import back.
- **Exams**: "I have a maths exam in 3-4 days" puts the exam in the calendar (reminder the day before; a range
  takes the earlier day) and offers a study plan; "topics: ...; 1 hour a day" spreads the topics over the days left,
  the last day a mock exam, every session in the calendar. New skill `exam-prep`, tool `study_plan`.
- **Birthdays, name days, anniversaries**: "Mum's birthday is on 12 March" - yearly, reminded the day before at
  09:00. "I forgot Peter's birthday, it was yesterday" - saved for next year, with an offer to write an apology.
- **Excel files look like real templates**: a title, an Excel table with filters, money / % / dates formatted, a totals
  row with SUM formulas, a chart when the data suits one (horizontal bars for long names), print settings.
- **PowerPoint files are designed**: a dark cover, an agenda for longer decks, big-number slides ("90% - ..."), two
  columns for many short points, text that grows when there is little of it, a footer with the page number.
- **Demo data**: `vaelon demo load` / "load demo data" adds made-up bills, a budget, deals, invoices (numbered
  DEMO-..., outside the real series) and calendar entries; "remove the demo data" removes only those.
- Skill `code-mentor`: explains code to someone learning, line by line, with exercises.
### Changed
- **Money is in euro** by default; amounts said in a former national currency of the euro area are converted at its
  fixed rate.
- The companion: the orb always fills from the centre (the far-away entrances left the small orb empty for
  seconds), and the five buttons fit the window (the last one was cut off).
- More spellings of the name are corrected: Waelon, Welon, Walon, Vealon.
### Security
- Text that looks like a formula (`=`, `+`, `-`, `@`) stays text in every Excel file Vaelon writes - a bank
  statement line or a client name can never run as a formula.

## 0.14.0 - 2026-11-15
### Added
- **Deals** (Money > Deals, `/deals`): the sales you are working on - client, what it is about, value, stage
  (lead 10 %, contacted 20 %, proposal 50 %, negotiation 75 %, won, lost), expected close date, a next step with a
  date and a log of notes. The pipeline shows the open value and the expected (weighted) value, late next steps,
  deals with no movement for two weeks, and won / lost / win rate this year.
- Vaelon reminds you on the day of a next step and once when an expected close date passes with the deal still open.
- A won deal becomes an invoice in one click (or "make the invoice for the Acme deal").
- Say it: "new deal with Acme: website 5000 EUR", "new deal with Globex for a mobile app 12000 EUR", "Acme is at
  the proposal stage", "move Globex to negotiation", "follow up with Globex on Friday about the contract", "follow up with Acme
  tomorrow: send the proposal", "we won the Acme deal", "Initech said no", "how are my deals going?" - answered at once. A question
  ("did we win Acme?") changes nothing, and a stage word only acts when a deal's client is named.
- The Excel export has a "Deals" sheet. Stored encrypted (`deals.enc`).

## 0.13.0 - 2026-11-15
### Added
- **Budget** (the ¤ button now opens "Money": Budget, Bills to pay, Paid, Invoices, My business; also `/budget`).
  Income and expenses, a monthly limit per category and an overall one, a bar per category (green, amber from 80 %,
  red over the limit). Paid bills count as spending by themselves, so nothing is typed twice.
- Say it: "spent 30 EUR on groceries", "spent 12 EUR on coffee yesterday", "got paid 2000 EUR salary", "set a budget
  of 400 EUR for groceries", "set a budget of 100 EUR for eating out", "how is my budget?", "how much is left for
  eating out?", "how much did I spend this month" - answered at once; an expense that takes a category past 80 % or past
  its limit says so in the same answer.
- Everyday categories guessed from words (groceries, eating out, transport, car, shopping, health, entertainment,
  education, gifts, travel, home, kids, pets, personal care) next to the bill categories.
- One budget currency (EUR by default); other currencies are listed apart.
- The Excel export has a third sheet, "Budget". Stored encrypted (`budget.enc`).
### Fixed
- "1 invoices waiting" now reads "1 invoice is waiting".

## 0.12.0 - 2026-11-15
### Added
- **Bills and invoices** (the ¤ button, `/bills`). Vaelon never pays anything: it keeps the list, reminds and
  writes documents; paying is always done by you, in your bank.
  - Bills to pay: who, how much, by when, a category (guessed: electricity, water, rent ...), a number, notes and a
    repeat (monthly, every 3 months, yearly). Paying a repeating bill adds the next one with the same amount as an
    estimate (`~`) until the real bill arrives. Reminders a few days before the due date (default 3), on the day,
    and once when it is overdue (only between 08:00 and 22:00).
  - Say it: "add a bill: electricity 45.20 EUR due 25.11", "add a bill: internet 25 EUR due 30.11", "I paid the electricity bill",
    "what bills do I have to pay?", "how much did I pay for electricity this year?", "who owes me?" - answered at once,
    without the model.
  - Read a bill from a PDF, Word file or photo: attach it and say "add this bill" (vendor, amount, due date and
    number are read from it; what could not be read is said).
  - Invoices you issue: one unbroken 10-digit series, your business details, items, VAT (with the legal note when
    no VAT is charged), a due date, a PDF made on this computer. An issued invoice is never
    deleted - it can be voided and its number stays used.
  - Totals by category, an Excel export (bills + invoices) for an accountant.
  - Stored encrypted (`bills.enc`); amounts are kept in cents, never in floating point.

## 0.11.0 - 2026-11-15
### Added
- **Calendar** (the ▦ button, `/calendar`): appointments with a time, a length, a place and notes; all-day events;
  repeats (daily, weekly, monthly, yearly - a 31st falls back to the month's last day); skip one date of a
  repeating event; overlap warnings; a reminder before each appointment (Windows notification + a line in the app).
  Stored encrypted (`calendar.enc`).
- Say it: "add a dentist appointment on Friday at 10", "add a meeting with Ana on 20.11 at 15:00", "what do I
  have tomorrow?", "what's on my calendar" - answered at once, without the model. The model has tools to add, list, find,
  move and cancel events.
- **.ics both ways:** export the calendar for Google Calendar, Outlook or a phone; import an .ics file from them.
- Times in words: weekdays ("on Friday", "next Monday"), dates ("20.11", "on 3.2.2027") and months ("20 November",
  "November 20") - reminders understand them too.

## 0.10.0 - 2026-11-15
### Added
- **Phone and email in Settings:** pick your email provider (Gmail, Outlook, Yahoo ...), enter your address, the
  app password and the Twilio details - all encrypted. Port 465 providers work too.
- **Contacts Vaelon can save:** "save Mum's number +1 555 0100" - kept encrypted (an old `contacts.json` is moved in).
- **The swarm never starts the same way:** a fresh random seed every start, six entrances (scatter, big bang,
  rain, ring, stream, spiral), a different tint and light wave, and - now and then while idle - figures: a sphere,
  a torus, a double helix, a galaxy, a wave and the dotted V of the logo, at random moments, sizes and angles.
### Changed
- **The app opens on a new conversation;** earlier ones are one click away in the list (❏).
- **The companion opens fully visible** (top right of the screen) and remembers where you put it. At 125 % or
  150 % display scaling it used to open almost completely off the screen.
### Fixed
- **"Valon":** speech recognition wrote the name as "Valon" and the model believed it. Whisper now gets the name as
  a hint, common mishearings are corrected (Valon, Vallon ... -> Vaelon) and the model is told.
- The swarm's animation runs on its own clock, so on a slow PC an entrance or a figure never ends before the
  particles get there.

## 0.9.0 - 2026-11-13
### Faster
- **The cloud voice (ElevenLabs) now streams:** a sentence starts to sound about 0.15 s after its first audio
  arrives, instead of after ElevenLabs has finished all of it - on a 10-second sentence about 2 s sooner (measured
  with a stand-in that generates at 4x real time). The Voice Designer effects were rebuilt to work piece by piece
  with the same sound (same length; the loudness curve matches the whole-clip version to 99.6-100 %).
- Checked once against the real ElevenLabs (61 characters): the stream and its audio format work. Its first audio
  came after about 0.9 s of generation plus 0.55 s for a new connection (opened in advance during a conversation);
  a short sentence then arrives almost at once, so streaming helps most with long sentences.
- The streamed voice's tools are loaded in the background right after start (when ElevenLabs is your voice),
  instead of costing about 0.3 s on the first sentence.
- A sentence that was already spoken comes from the cache: no new request, no credits. If ElevenLabs refuses or
  cannot be reached before sending audio (nothing billed), the local voice answers - with no second cloud attempt.
- When you interrupt, the app stops reading the stream and the core closes the connection to ElevenLabs.
### Fixed
- **The voice could start the whole answer again from the beginning** when the finished answer differed from the
  streamed one only by a space at the end. Now it only starts over when the text really changed.

## 0.8.0 - 2026-11-13
### Faster
- **Spoken exchanges start about half a second sooner.** With a cloud speech-to-text engine, transcription begins at
  the first short pause instead of after the full 0.7 s of silence; if you go on talking, that attempt is dropped.
  The same audio goes to the same engine as before, only a moment earlier.
- **Connections are ready when you finish.** The moment you start talking or typing, the core opens the HTTPS
  connections your request will need (speech-to-text, model, cloud voice - only services you already chose). The
  request that does it is empty: no key, no text, no audio. One shared keep-alive pool serves all three calls.
- **The local voice is ready sooner and its first sentence is quicker:** both voices load side by side (about
  3.5 s instead of 5.5 s on the reference PC) and each runs once while warming up, so the first real sentence takes
  0.25 s instead of about 0.6 s.
- **The window appears about 0.6 s sooner:** the voices now load right after the window has opened, not
  during start-up.
- **Spoken "what is ..." questions to a cloud model skip the Wikipedia pre-fetch** (about half a second); the
  model can still look things up itself. Typed questions, questions about people and local models keep it.
### Added
- **`/speed`:** after every answer, a line shows how long each part took after you finished - your words as text,
  the first words of the answer, the first sound of the voice. Measured on your own PC with your own services.

## 0.7.0 - 2026-11-12
### Added
- **MCP connections:** Vaelon can use tools from outside programs and services that speak the Model Context
  Protocol (`vaelon mcp add ...`). Its own client, no SDK: local servers (stdio) and remote ones (Streamable
  HTTP), both the 2026-07-28 revision and the older handshake-based ones. You approve a server and its tools once;
  every call still asks you; a tool the server changes afterwards is blocked; results are treated as outside data.
- **Settings in the app** (the gear button, `/settings`): your name, the model provider and model, API keys,
  voice and speech-to-text engines, the ElevenLabs monthly limit, learning on/off; shows the data sources and the
  connected MCP servers. **Keys can be entered in the app:** they go straight into the encrypted vault, are never
  shown again and no part of the API can read them back.
- **First-run setup:** a brand-new installation is asked for a name and where to think (this PC, with a check that
  Ollama and the model are there, or a cloud provider with your own key). Every step can be skipped.
- **Several conversations:** a list of chats (the ❏ button, `/chats`, `/new`) - open, rename, delete. Each chat
  and the list of titles are encrypted; the earlier single history becomes the first chat. The window opens on the
  chat that was open last.
- **More reliable web search:** a chain of sources - Tavily and Brave Search with a free key (official APIs), the
  public engines without a key, Wikipedia as the last resort. Results are de-duplicated, spread over sites and
  ordered by match; questions about "today" or "news" ask for recent results. When no engine answers, Vaelon says
  so instead of pretending nothing exists.
- **Stock data from official sources:** with a free Twelve Data and/or Finnhub key Vaelon uses them before
  Yahoo Finance (which stays the keyless fallback); a failing source hands over to the next and every answer
  names where its numbers came from. Keys go in a request header and only to their own host.
- **App icon:** the dotted V on Vaelon.exe, both app windows, the installer and the browser tab
  (`scripts/make_icons.py` rebuilds it from `brand/logo-v.webp`).

## 0.6.0 - 2026-11-11
### Added
- **Live voice** in the companion (the bolt button): real-time conversation through Gemini Live - answers in
  about 1.5-2 s, can be interrupted, and sees the screen continuously when the eye is on. Opt-in; the microphone
  audio goes to Google while it is on. The key stays in the core (local bridge); everything real is still done by
  Vaelon's own agent with its approvals.
### Changed
- The Gemini provider preset uses a model that new keys can reach.

## 0.5.0 - 2026-11-10
### Changed
- **The project is now called Vaelon.** Package, command (`vaelon`), app (`Vaelon.exe`), data folder (`~/.vaelon`)
  and created files (`Documents/Vaelon`) carry the new name. Data written by earlier private builds is moved over
  automatically at the first start; keys, memory and history keep working unchanged.

## 0.4.0 - 2026-11-10
### Added
- **The companion:** hands-free now opens a small always-on-top window you can drag anywhere - a live orb, your
  words, the answer, and buttons for microphone, stop and back-to-full-window.
- **It can see your screen:** with the eye switched on, questions about what is on the screen are answered from a
  screenshot (no extra approval while the eye is on; never after outside content entered the task).
### Changed
- No more false warning for Google API keys that do not start with "AIza".

## 0.3.0 - 2026-11-09
### Added
- **Create files:** Word, PDF, Markdown and text documents, Excel spreadsheets, PowerPoint presentations, and spoken
  audio / two-voice podcasts (local voice). File cards in the chat: Open, Show in folder, Play.
- **Deep research:** `/research <topic>` - parallel searches and page reads, a report with real numbered sources,
  saved as a Word file.
- **Reminders** ("remind me in 20 minutes to ...") with Windows notifications and in-app notices; scheduled tasks
  can be set from the chat and report back the same way.
- **Attachments and vision:** attach pictures and documents (paperclip, paste, drop); cloud vision on Groq.
- Reading of .xlsx and .pptx documents.
### Changed
- Vaelon refuses to invent the content of a file, picture, order or account it was not shown.

## 0.2.0 - 2026-11-09
### Added
- **Several tasks at once.** Up to four requests run at the same time, each on its own agent. The swarm splits into
  one cluster per task (own colour, own shape); click a task's label to see every step it has taken, its answer as
  it is written, and to cancel it. Finished tasks burst and the matter flows back into one body.
- **Hands-free conversation** (`hands-free` button or `/talk`). The microphone stays open: speak, Vaelon answers
  aloud, speak over it to interrupt, say "stop" to cancel. Spoken answers are short by design.
- **Several lookups in one step.** When a cloud model asks for several read-only tools at once they run in parallel.
- **Lookup cache.** Repeated searches, pages, weather and prices are reused for a short time.
- `vaelon about`, an About tab, `vaelon update`, `/stop`, `POST /cancel`, `GET /jobs`.
- Project files for publishing: CONTRIBUTING, CODE_OF_CONDUCT, PRIVACY, release workflow, installer script.

### Changed
- **License: GPL-3.0-or-later** with an author-attribution term (see `NOTICE`). Earlier, unpublished versions were
  marked Apache-2.0.
- "Compare A and B" questions go to the model instead of a single live source.
- Keep-alive connections for the cloud voice and cloud speech-to-text.

## 0.1.0
First private version: local-first agent, tools, safety model, vault, voice designer, desktop app.
