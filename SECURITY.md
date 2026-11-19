# Security

## Reporting a vulnerability
Please report security problems **privately**: use the repository's "Report a vulnerability" page (GitHub Security
Advisories). Do not open a public issue and do not include real keys, tokens or personal data in a report.
You will get an answer as soon as the maintainer can read it; fixes are released before details are published.

## What counts
Anything that lets outside content or another program make Vaelon act without the user's approval, read or leak the
vault, the conversation, memory or keys, bypass the risk/approval system, or run code that the user did not approve.

## How Vaelon protects you (summary)
- The API listens on 127.0.0.1 only, holds its port exclusively, needs a random bearer token, checks the Host header
  and refuses every request from a web page that is not Vaelon's own. The app checks that the core proves it knows the
  key before it sends anything (another program on the port learns nothing); the Live voice bridge does the same both
  ways.
- After outside content entered a task, an address the model made up, remembering, forgetting, undoing and handing work
  to a specialist need approval; writing programs or into places where files start by themselves always does. The
  approval card shows the whole action and answers only that card.
- Dangerous actions need a human approval that the model cannot forge; outside content taints a task and tightens it.
- Keys live in an encrypted vault (DPAPI + AES-256-GCM), are bound to their provider's host, and are scrubbed from
  logs, memory, model input and tool output.
- File tools can never touch `~/.vaelon`. Downloads are scanned. Code integrity is signed and verified at start.

- Your own data cannot leave through a search after outside content without your approval; approval cards cannot
  hide characters or the end of a long action; encrypted files never accept plain text; security settings changed in
  config.json by something else are ignored and reported; code changes outside approved updates are reported in the app.
- Tested on purpose: a full code review by five reviewers and two white-hat penetration tests (2026-11-16 and
  2026-11-18). Known limit: anything running under YOUR Windows account can read what you can read - use separate
  Windows accounts for real separation.

## Checking a download
Every release lists a SHA-256 for each file. Compare before you run it:
```powershell
Get-FileHash .\Vaelon-Setup.exe -Algorithm SHA256
```

Never commit keys. Run `python scripts/check_secrets.py` before every commit.
