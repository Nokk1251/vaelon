# Master prompt for the Vaelon website (paste into Claude, Artifacts on)

Attach these three pictures to the same message first: `brand/hero-3.webp`, `brand/wordmark.webp`, `brand/logo-v.webp`.
Then paste everything between the lines.

---

Build the official one-page website for **VAELON** as a single, self-contained HTML artifact (HTML + CSS + vanilla
JavaScript in one file, no frameworks, no external libraries, no web fonts, no trackers, no cookies, no forms that send
data anywhere). All text on the site is in **English**.

## What Vaelon is (use only these facts - do not invent features, numbers, users, reviews, prices or awards)
Vaelon is a private, open-source AI assistant for Windows that lives on your own computer. You talk to it by text or by
voice, and it does real work: it answers, searches, writes files, keeps your calendar and money in order, and learns
how you work. It is free software (GNU GPL v3 or later), originally created by **Nokk_7**.

Core promise: **privacy first.** By default everything runs on your PC with a local model (Ollama). Cloud models and
cloud voices are optional, used only with your own key, and the app says clearly that text then leaves the PC. No
accounts, no telemetry. Keys, memory, chats, calendar, money and contacts are stored encrypted (AES-256-GCM + Windows
DPAPI).

Features (group them into 6-8 feature cards, short and concrete):
- **Talk to it**: hands-free conversation you can interrupt; a small always-on-top companion window; optional
  real-time Live voice; a Voice Designer (pitch, speed, metal, radio, echo ...). Local neural voices are free and
  private.
- **Knows the live world**: weather, stocks, crypto, exchange rates, news, Wikipedia, scientific papers - instant
  answers without waiting for the model; deep research with sources (`/research`).
- **Makes real files**: Word, PDF, Excel and PowerPoint that look human-made, and spoken audio/podcasts; attach a
  picture or document and ask about it.
- **Money, done right**: bills with reminders, invoices with an unbroken numbering, a monthly budget with limits, a
  sales pipeline of deals, bank statement import (CSV). Amounts in euro. **Vaelon never pays or touches your bank.**
- **Thinks one step ahead**: "I have an exam in 4 days" becomes a calendar entry and a study plan; birthdays repeat
  every year with a reminder the day before; a calendar with .ics import/export.
- **Company mode (optional)**: separate companies, people with roles and a PIN, a lock button, and a tamper-evident
  journal of who changed what.
- **Profiles (optional)**: Business, Learning, Coding, Creator, Everyday life - pick what you use it for, or nothing.
- **Connects to your tools**: MCP servers (for example accounting software), email, phone/SMS, Telegram - every
  message or call is sent only after you approve it.
- **Safe by design**: anything that changes or sends something waits for your Allow; content from the web or a file
  can never approve anything; a page that tries to steer it is fenced as data; self-learning never learns from
  outside content; the code is signed and checked at start.

## Brand and look
- Name: always **VAELON** (all capitals in headings, "Vaelon" in running text). Never any other spelling.
- Mood: cinematic, dark, futuristic but calm and trustworthy - an AI that is powerful AND on your side. Think a
  glowing ember swarm in the dark, not a cartoon robot.
- Colours (use exactly these as CSS variables): background `#050304`, panels `#120a0a`, accent ember `#ff7a1f`,
  rare alert red `#ff1f2d`, text bone `#efe6df`, muted text `rgba(239,230,223,0.55)`, lines
  `rgba(255,122,31,0.22)`. Glass panels with a subtle blur and a thin ember border.
- Fonts (system fonts only): headings and UI labels `ui-monospace, "Cascadia Code", "JetBrains Mono", Consolas,
  monospace` with wide letter-spacing in uppercase; body text `"Segoe UI Variable", Inter, system-ui, sans-serif`.
- Images (they will be served next to the HTML file, reference them by these exact relative names):
  - `hero-3.webp` - the hero background (full width, darkened gradient over it so the text stays readable);
  - `wordmark.webp` - the VAELON wordmark: it MUST be big and prominent in the hero, and appear again small in the
    footer;
  - `logo-v.webp` - the small logo for the header and the favicon.
  If an image is missing (as in this preview), the page must still look finished: behind the hero draw an animated
  ember particle swarm on a `<canvas>` (a few thousand small orange dots slowly orbiting and breathing, lightweight,
  paused when the tab is hidden and when `prefers-reduced-motion` is set), and show the word VAELON in large spaced
  monospace letters instead of the wordmark.

## Page structure
1. **Header** (sticky, slim): logo + VAELON, links: Features, Privacy, How it works, FAQ, Download.
2. **Hero**: the wordmark, the line "Your private AI. On your computer. On your side.", one short sentence under it,
   two buttons: "Download for Windows" and "See what it can do". Small honest note under the buttons: "Free and
   open source · Windows 10/11 · works offline with a local model".
3. **Features**: the cards above, each with a simple inline SVG icon (draw them yourself, ember line style).
4. **Privacy**: a two-column comparison "Stays on your PC" (everything by default) vs "Leaves only if you choose" (a
   cloud model you pick, a cloud voice, web searches, messages you ask it to send). Calm, factual tone.
5. **How it works**: 3 steps - Install, Choose where it thinks (this PC or a cloud model with your own free key),
   Talk or type. Mention that Settings and a short first-run setup guide you, and that the ? button explains everything.
6. **Safety**: a short visual of the approval card idea: "Vaelon wants to: delete report.pdf permanently - Allow /
   Deny", with the explanation that the model can never press Allow for you.
7. **FAQ** (accordion, keyboard accessible): Is it free? Does my data leave my PC? Which computer do I need? (a normal
   Windows PC; a local model is slower on a weak CPU, a free cloud key makes it fast) Can it pay bills? (no, it only
   keeps track) Can it be used by a small company? Is it open source? (yes, GPL-3.0-or-later; the source will be
   published on GitHub).
8. **Download**: the release is not public yet - show the button as "Coming soon" (disabled look) with the line "Want
   to know when it is out? Follow the author on GitHub" linking to https://github.com/Nokk1251 . Do NOT invent version
   numbers, file sizes, download counts or checksums.
9. **Footer**: small wordmark, "Vaelon - originally created by Nokk_7" (link https://github.com/Nokk1251), "Free
   software under the GNU GPL v3 or later", "No cookies. No tracking." and the year.

## Quality bar
- Looks like a premium product site made by a human designer, not a template: generous spacing, a clear rhythm,
  restrained use of the accent colour, no emoji, no stock-photo clichés, no fake testimonials, no lorem ipsum.
- Fully responsive (looks great at 360 px phone width and at 1440 px), no horizontal scroll, 16 px side padding on
  phones.
- Accessible: semantic HTML (header, main, section, footer, h1-h3 in order), visible focus styles, alt text on images,
  enough contrast, respects `prefers-reduced-motion`.
- Subtle motion only: fade/slide-in on scroll with IntersectionObserver, a soft glow on hover. Fast: no heavy effects.
- Smooth-scroll anchor links; the header highlights the current section.
- Valid, tidy code with short comments; everything in ONE file.

---
