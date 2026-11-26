# Privacy

Vaelon is built to keep your data on your computer. This page says exactly what is stored, what can leave the
machine, and when.

## What stays on your computer (always)
| Data | Where | Protection |
|---|---|---|
| Conversations and their titles | `~/.vaelon/chats/` | AES-256-GCM, one encrypted line per message |
| Calendar, contacts, reminders | `~/.vaelon/calendar.enc`, `contacts.enc`, `reminders.enc` | AES-256-GCM |
| Bills, invoices, business details | `~/.vaelon/bills.enc` | AES-256-GCM |
| Budget: income, expenses, limits | `~/.vaelon/budget.enc` | AES-256-GCM |
| Deals: clients, values, notes | `~/.vaelon/deals.enc` | AES-256-GCM |
| Company mode: people (PIN hashes), companies | `~/.vaelon/company.enc` | AES-256-GCM |
| Each company's money data and journal | `~/.vaelon/workspaces/<id>/` | AES-256-GCM (journal: + HMAC chain) |
| Long-term memory, your profile | `~/.vaelon/memory.db`, `profile.enc` | AES-256-GCM, search over a blind index |
| API keys | `~/.vaelon/secrets` | AES-256-GCM; sealed by Windows DPAPI (bound to your Windows account) or, on a Mac, by a key kept in the macOS Keychain |
| Audit log of what Vaelon did | `~/.vaelon/audit.jsonl` | HMAC-chained; what you wrote (requests, answers, tool arguments) AES-256-GCM, secrets scrubbed |
| Scheduled tasks and their results | `~/.vaelon/schedule.enc`, `inbox.enc` | AES-256-GCM |
| Feedback notes you write in Help | `Documents\Vaelon\Feedback\*.txt` | plain text you can read before sharing - never sent by itself |
| Voice profile, settings | `~/.vaelon/config.json` | no secrets inside |

Microphone audio is kept in memory only while it is being transcribed. It is never written to disk.
Erase at any time: `/clear` in the app (the open conversation), the ❏ list (any conversation), the ▦ calendar
(any appointment), `vaelon memory wipe` (memory and every conversation), or delete `~/.vaelon`.

## What can leave your computer - only if you turn it on
| You chose | What is sent | To whom |
|---|---|---|
| A cloud model (`vaelon provider groq`, gemini, openrouter, ...) | Your message, recent conversation and tool results | That provider |
| Groq as provider + the microphone | The recorded phrase (for speech-to-text). In hands-free mode it may be sent at a short pause already, and again if you go on talking - the same audio, a moment sooner | Groq |
| ElevenLabs voice | The text that is spoken (at most ~600 characters per answer) | ElevenLabs |
| Live voice (the bolt in the companion) | Your microphone audio, continuously while it is on; with the eye on, a picture of your screen every few seconds | Google (Gemini Live) |
| Screen sharing (the eye) without Live | A screenshot, only when you ask about the screen | Your cloud model |
| Ask your folder (Settings > Your folders) with a cloud model | The few passages of your documents that answer a question, with the question. The index itself stays on this computer, encrypted (`library.enc`) | Your cloud model |
| A search key you stored (Tavily or Brave Search) | The search words of a web search - never the conversation | That search service |
| An MCP server you added (`vaelon mcp add`) | What Vaelon passes to its tools - shown to you before every call unless you allowed that tool | That program or service |
| Telegram, email, SMS, calls | The messages you ask Vaelon to send | Telegram / your mail server / Twilio |
| The update check (Settings > Updates: off by default; or **Check now**, `vaelon update`) | Nothing about you: one request for the newest version number - at most once a day (also across restarts); **Check now** / `vaelon update` at most once a minute. GitHub sees your IP address, as any website does. Nothing is downloaded or installed by itself | GitHub |

With the default local setup (Ollama model, Piper voice, local Whisper) none of the above happens.
When you start talking or typing, Vaelon may open a connection to the cloud services you have chosen so that it is
ready when you finish. That request is empty (no key, no text, no audio); with the local setup it is not made.
Before text goes to a cloud model it is scrubbed of anything that looks like a key or password, and your stored keys
are removed by exact value. Each key is only ever sent to its own provider's server.

Your calendar stays on this computer, encrypted (`calendar.enc`). It is not synced with any service; an .ics
file you export is an ordinary file - where it goes is up to you.

Bills, invoices and your business details stay on this computer, encrypted (`bills.enc`). Vaelon never pays
anything and never connects to a bank. A bill read from a photo goes to your vision model like any other picture
(local, or your cloud provider if you chose one); a PDF or Word bill is read on this computer.

A bank statement you import is read on this computer; only the transactions go into the encrypted budget, the
CSV file stays where you put it. Vaelon never connects to a bank and never pays.

## Lookups you ask for
When you ask about the weather, a stock, Wikipedia or the web, Vaelon contacts that public source (Open-Meteo,
Yahoo Finance or - with your own key - Twelve Data / Finnhub, CoinGecko, Wikipedia, public search engines, ...) with the search words only - never your identity or history.

## What Vaelon never does
- No telemetry, analytics, crash reports or advertising IDs.
- No account, no registration, no cloud sync.
- No background uploads. The update check (`vaelon update`) is one anonymous request to the public release page,
  and only after the project has a public repository.

## Your keys, your accounts
Vaelon does not come with shared keys. If you use a cloud service you use your own key, under that service's own
privacy policy. Read it before you paste sensitive text.
