// The Help page: everything explained in one place, so the screens themselves can stay short.
// Markdown, rendered by components/Rich (no raw HTML). Keep it true to what the code does.

export type HelpSection = { id: string; title: string; body: string };

export const HELP: HelpSection[] = [
  {
    id: "start",
    title: "Getting started",
    body: `Vaelon is an assistant that runs on **your** computer. Type what you want in the command box, or talk to it.

- **☰ Menu**: example requests you can click, every tool, skill and command.
- **Slash commands**: type \`/help\`, \`/new\`, \`/chats\`, \`/calendar\`, \`/budget\`, \`/settings\`... in the command box.
- **Several tasks at once**: send a new request while one is running. Up to four run at the same time. Click a task's label to see its steps or stop it.
- **Undo**: say *"undo"* to take back the last change Vaelon made (a file, a bill, a contact...).
- Vaelon answers in the language you write in. Simple questions (time, weather, prices, *"what bills do I have"*) are answered at once, without the model.

**Starting Vaelon**: Windows - Start menu > Vaelon. Mac - Applications > Vaelon (or Spotlight). The first time on a Mac, macOS asks you to allow it: System Settings > Privacy & Security > **Open Anyway**.

**A model is needed** for conversations, files and research: install the free Ollama app (Settings has a **Get Ollama** button), then pick a model there - the list says what each one is good for, how much memory it needs and whether it fits this computer - and press **Download the model**, or add a cloud key in Settings. See *Where the thinking happens*.`,
  },
  {
    id: "profiles",
    title: "Profiles (optional)",
    body: `A profile tells Vaelon what you mostly use it for. Pick none, one or several in **Settings → Profiles**, and change them whenever you like.

| Profile | Good for |
|---|---|
| Business | bills, invoices, budget, deals, meetings |
| Learning | lessons, exam plans, explanations, practice tests |
| Coding | writing and checking code, project files |
| Creator | reports, slides, spreadsheets, podcasts, research |
| Everyday life | reminders, calendar, birthdays, household budget |

A profile only does three things:
1. a few of its tools are always ready, so they work even when you do not use the usual words;
2. Vaelon gets one short line about how you like to be helped;
3. its examples come first in the menu.

Nothing is switched off: every other tool still works. A profile never gives extra rights.`,
  },
  {
    id: "voice",
    title: "Voice: talking to Vaelon",
    body: `- **Microphone button**: say one request.
- **Hands-free** (\`/talk\`): a conversation. Talk, listen, interrupt it by speaking. Say *"stop"* to end.
- **Companion**: the small round window that stays on top of other programs. It can listen, talk and, if you turn on the eye, look at your screen.
- **Live voice (the bolt ⚡ in the companion)**: real-time conversation through Google Gemini Live. It needs a Gemini key, and your voice goes to Google while it is on.
- **Eye**: lets Vaelon look at your screen when a question is about it. It works only while it is switched on.
- **Voice designer** (◉): pitch, speed and effects of Vaelon's voice. The local voices are free and private. ElevenLabs voices are cloud and have a monthly cap (Settings → Voice).

The installed app speaks with your computer's own voice. If a language has no voice, add one: Windows Settings > Time & language > Speech; Mac: System Settings > Accessibility > Spoken Content > System voice > Manage voices. (With a source install, \`vaelon voice-setup\` adds the private neural voices.)`,
  },
  {
    id: "models",
    title: "Where the thinking happens: models and keys",
    body: `- **Local** (Ollama): everything stays on this PC. It is slower on a weak computer.
- **Cloud** (Groq, Gemini, OpenRouter, Mistral...): much faster. **Your text is sent to that company.** It needs your own API key; most have a free tier.

Keys are entered **only** in Settings (or with \`vaelon key set NAME\` in a terminal), never in the chat. A key goes straight into the encrypted vault on this computer. It is never shown again and is only ever sent to its own service. Rotate a key after 90 days (Settings marks old keys).`,
  },
  {
    id: "files",
    title: "Files, documents and attachments",
    body: `- *"Write a report about ... and save it as PDF"*, *"Make an Excel table ..."*, *"Create a 6-slide presentation ..."*: Vaelon makes the file and shows a card with **Open** and **Show in folder**.
- Created files go to **Documents/Vaelon** (in company mode: *Documents/Vaelon/Companies/<company>*). Nothing is ever overwritten.
- **Paperclip**: attach a document or a picture. *"What is in this picture?"*, *"Summarise this PDF"*, *"Add this bill"*.
- Vaelon asks before it deletes, moves or overwrites anything outside its own folder.`,
  },
  {
    id: "money",
    title: "Money: bills, invoices, budget, deals",
    body: `Open it with **¤** or \`/budget\`, \`/cashflow\`, \`/bills\`, \`/deals\`. **Vaelon never pays anything and never connects to a bank.** "Paid" only marks a bill.

- **Bills**: *"Add a bill: electricity 45.20 EUR due 25.11"*, *"I paid the electricity bill"*, *"What bills do I have to pay?"*. Vaelon reminds you a few days before, on the day, and when a bill is late (08:00-22:00 only).
- **Invoices**: fill in **My business** first (name, ID, VAT, bank). Invoices get an unbroken 10-digit number. They are never deleted: *void* keeps the number.
- **Budget**: *"Spent 30 EUR on groceries"*, *"Set a budget of 400 EUR for groceries"*, *"How is my budget?"*. A warning comes at 80 % of a limit. Paid bills count by themselves.
- **Cash flow**: the next 30, 60 or 90 days, week by week: unpaid invoices and bills, the next bills of repeating ones, and your usual income and spending (estimates). Type the money you have now to see each week's balance and a warning when it may run short. *"How does my cash flow look?"*, *"Can I afford 2000 EUR next month?"*. Open deals are shown apart and never counted.
- **Bank statement**: download the CSV from your online banking and use **Import bank CSV** (you see a preview first). Lines already imported are skipped, and payments that match a bill mark it paid.
- **Deals**: *"New deal with Acme: website 5000 EUR"*, *"Move Acme to proposal"*, *"We won the Acme deal"*, *"Make the invoice for the Acme deal"*.
- **Excel**: *"Export my money to Excel"* gives one file with Bills, Invoices, Budget and Deals sheets.
- **Demo data**: *"Load demo data"* fills everything with made-up examples. *"Remove the demo data"* deletes only those.

Amounts are kept in euro by default; the budget can use another currency.`,
  },
  {
    id: "calendar",
    title: "Calendar, reminders and life events",
    body: `- *"Add to my calendar: dentist on Friday at 10"*, *"What do I have tomorrow?"*, *"Remind me in 20 minutes to call mum"*, *"Every day at 08:00 give me a morning briefing"*.
- Vaelon thinks one step ahead:
  - *"I have a history exam in 4 days"* adds the exam and a reminder the day before;
  - *"Topics: WW1, WW2, the Cold War; 1 hour a day"* then spreads the topics over the days left, with a mock exam on the last day;
  - *"Mum's birthday is on 12 March"* repeats every year, with a reminder the day before;
  - *"I forgot Peter's birthday"* sets next year's reminder and offers to write an apology.
- **▦ Calendar**: the next two weeks, add or cancel, export to .ics (Google / Outlook can import it).
- Reminders arrive as system notifications (Windows or Mac) while Vaelon is running (the companion counts too).`,
  },
  {
    id: "company",
    title: "Company mode: people, roles, journal",
    body: `Off by default. Turn it on in **Money → Company** (your name and a 4-8 digit PIN). You become the owner.

- **Companies**: each one has its own bills, invoices, budget, deals, journal and file folder. Your personal space stays yours.
- **People and roles**:

| Role | May |
|---|---|
| Owner | everything |
| Accountant | bills, invoices, budget, bank import, Excel, journal; sees deals |
| Sales | deals; sees invoices |
| Member | records expenses and income |
| Viewer | only looks |

- **Lock**: the button next to the company name. A locked Vaelon answers nothing until someone signs in with their PIN. Five wrong PINs lock sign-in for 1 minute, then 2, 4, 8... up to an hour.
- People who are not the owner never reach your memory, chats, calendar, files, mail, settings or keys. Their requests run in a work mode with only the money and lookup tools.
- **Journal**: who changed what and when. It is encrypted and chained, so a changed, deleted or older copy of it is detected.

Honest limit: on **one computer account** (Windows or Mac) this protects against mistakes and curious colleagues, not against someone who can use that account directly. For real separation give everyone their own account.`,
  },
  {
    id: "comms",
    title: "Email and phone",
    body: `Set them up in **Settings → Phone and email**. Vaelon **asks you before every email, SMS or call**.

- **Email**: choose your provider and enter your address and an **app password**. Gmail and Outlook need 2-step verification. Then create an app password in your account's security settings. Never use your normal password.
- **Phone / SMS** go through Twilio, which gives you the number Vaelon calls from. It is paid per message or minute. A trial account reaches only numbers you verified there.
- **Contacts**: *"Save Mum's number +1 555 0100"*. They are kept encrypted. Then *"Call Mum"* or *"Email Mum that I'll be late"*.`,
  },
  {
    id: "mcp",
    title: "Connected tools (MCP) and accounting programs",
    body: `MCP servers are outside programs that give Vaelon new tools, for example a filesystem, GitHub, or accounting. They run with your user rights, so they are added **only in a terminal**, where you see exactly what will run:

\`vaelon mcp add NAME -- command ...\` (also \`vaelon mcp list | allow | refresh | remove\`)

Every tool of a server is fingerprinted. If the server later changes a tool, Vaelon blocks it. Results from MCP tools are treated as outside content.

**Accounting**: Xero and QuickBooks Online have official MCP servers (see *docs/ACCOUNTING.md*). For other programs, use the Excel export.`,
  },
  {
    id: "safety",
    title: "Safety and privacy",
    body: `- **Approval cards**: anything that changes or sends something (deleting files, running commands, mail, calls) waits for your **Allow**. The model cannot approve for you.
- **Outside content**: after Vaelon reads a web page, an email or a file from elsewhere, the task is marked and every action needs your approval, even ones you normally allow.
- **Encrypted on this PC**: keys, memory, chats, contacts, calendar, money, company data (AES-256; the master key is sealed by Windows DPAPI or the macOS Keychain).
- **What leaves the PC**: only what you chose. That is a cloud model, cloud voice, web searches, the update check if you turn it on, and mail or phone when you send. With the local model and local voice, nothing about you leaves the computer.
- Vaelon's own source files carry an integrity signature (the installers themselves are not code-signed). From a source install, \`vaelon doctor\` checks the setup and \`vaelon integrity verify\` checks the code.
- On a Mac, macOS may ask once after an update whether Vaelon may use its Keychain item: choose **Always Allow**. If you deny it, nothing is lost - Vaelon just cannot open its vault until you allow it.`,
  },
  {
    id: "memory",
    title: "Memory and learning",
    body: `- *"Remember that my birthday is on 13 July"*, *"What do you know about me?"*, *"Forget ..."*.
- Vaelon notices your name, city, work and likes when you mention them (Menu → Memory shows it).
- **Self-learning** (Settings → Learning): after longer tasks Vaelon saves reusable skills and lessons. It never does this from tasks that read outside content.
- *"Learn about electric cars"*: Vaelon researches a topic and keeps the facts (marked unverified).
- \`vaelon memory wipe\` erases memory and all chats.`,
  },
  {
    id: "folders",
    title: "Ask your folder",
    body: `- Settings → **Your folders** → add a folder (it must be inside the folders Vaelon may use). Vaelon reads the PDF, Word, Excel, PowerPoint, text and Markdown files in it.
- Then just ask: *"When does my lease end?"*, *"What do my course notes say about photosynthesis?"*, *"Which contract mentions a notice period?"*. The answer names the file it came from - and says so when the documents do not contain it.
- **Private:** the index is kept on this computer, encrypted. With the local model nothing leaves the computer. With a cloud model, the few passages that answer a question are sent to it together with the question.
- **Safe:** text inside a document is treated like a web page - it can inform an answer but never give Vaelon orders. Hidden files, links pointing elsewhere, files that are only in the cloud (OneDrive) and sensitive files (keys, passwords, recovery codes, wallets) are skipped; keys and card numbers inside a document are blanked.
- **Your own links:** a link that appears only in your files or mail is opened only after you say yes - a planted document could use links to carry your data out.
- Changed files are read again in the background (at most every few minutes; the question being asked uses what was read before), or at once with **Read changes now**. **Remove** deletes the folder's index (not your files).
- Search is by words for now, so use words that appear in the documents.
- From a source install: \`vaelon library add <folder>\`, \`vaelon library ask "question"\`.`,
  },
  {
    id: "updates",
    title: "Updates",
    body: `- **Off until you turn it on.** Settings → Updates → *Check once a day* (also across restarts). Or press **Check now** (at most once a minute).
- The check asks GitHub, where Vaelon is published, for the newest version number. Nothing about you is sent. GitHub sees your IP address, as any website does.
- Vaelon never downloads, installs or runs an update by itself. It shows the version and a link to the official download page.
- To update: download the installer there and run it over your version. Your data, keys, chats and settings stay. Compare the file's SHA-256 with the one listed on that page.
- From a source install: \`vaelon update\` checks once.`,
  },
  {
    id: "trouble",
    title: "When something does not work",
    body: `- **Slow answers** with the local model: that is the computer's speed (the model runs on the CPU). A cloud model in Settings is much faster.
- **"Core offline"**: close Vaelon and start it again (from a source install: \`vaelon app\`).
- **Ollama is not answering**: install it with **Get Ollama** in Settings and start it (on a Mac it shows a llama in the menu bar).
- **The local model is missing**: press **Download the model** in Settings (or run \`ollama pull <model>\` in a terminal).
- **The moving swarm is missing** (a still glow instead): the graphics could not be used just then - often very
  little free memory or a graphics driver reset. Vaelon tries again every few seconds by itself; closing other programs
  or restarting Vaelon helps, and updating the graphics driver if it keeps happening. Everything else works without it.
- **No voice**: add a system voice for that language (see *Voice*).
- **The microphone does not hear you**: Windows - Settings > Privacy & security > Microphone, allow desktop apps. Mac - System Settings > Privacy & Security > Microphone, switch Vaelon on. In the companion, click once to allow audio.
- **Web search finds nothing**: the free search engines limit how often they answer. Wait a minute, or add a Tavily or Brave key in Settings.
- From a source install, \`vaelon doctor\` checks everything and tells you what to fix.`,
  },
];
