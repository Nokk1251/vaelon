# Analysis of the 7 source projects and what Vaelon took from each

| Project | Stack / License | What it is | Taken into Vaelon |
|---|---|---|---|
| **OpenJarvis** (Stanford) | Python, Apache-2.0, ~2200 files | Local-first agent framework: engines, agents, 30+ channels, security, skills, scheduler, CLI | Architecture: tool registry, capability/risk policy, guardrails (secret + PII + injection scanners), SSRF guard, audit log, TOML/markdown skills, agent roles, channel model (Telegram/Twilio), `doctor` CLI |
| **isair/jarvis** | Python, custom license | Voice-first private assistant, Whisper + Ollama, diary/graph memory | **Privacy doctrine**: local-first, redact before model context/diary, untrusted web content fenced as data, wake-word-then-process (non-addressed speech discarded), spec-per-module discipline, no vendor-locked cloud as the only path |
| **Priler/jarvis** | Rust+Tauri+Svelte, **CC BY-NC-SA** | Offline voice assistant (Vosk, wake word) | Idea only: 100% offline voice path (Vaelon uses faster-whisper). **No code copied** - NC-SA is incompatible with an Apache project |
| **AbuZar-Ansarii/Ultron** | Python/PyQt, **no LICENSE file** | MCU-Ultron persona, 51 tools, Gemini Live, HUD, Telegram remote, self-evolving tools, confirm gate, undo stack | Persona, action auto-discovery (`@tool`), **unforgeable confirmation** (UI-issued, not a model parameter), **undo stack**, self-evolution (`create_tool` with AST validation + human review), Telegram remote. **Deliberately not taken**: bounty hunter, BLE/RF recon, ghost mouse takeover, biometric sentry (offensive / privacy-invasive). No code copied (no license) |
| **modelscope/ultron** | Python/FastAPI, Apache-2.0 | Collective memory/skill/harness hubs, skill self-evolution | `SKILL.md` format with frontmatter; memory -> skill crystallisation idea (roadmap); tiered recall. Collective *remote* sharing intentionally excluded (privacy) |
| **sagar-builds/ultron** | Next.js/Three.js, MIT | Holographic orb UI with hand tracking | First UI was derived from it; fully replaced in v0.2 by the original Swarm UI (`ui/web`) |
| **microsoft/JARVIS** | HuggingGPT/EasyTool/TaskBench, MIT | LLM as controller planning tool use | Planning approach: model decomposes goal into tool calls; `delegate` to specialist agents; loop guard |

## Design decisions
1. **Privacy first**: Ollama default; cloud models receive secret-scrubbed text only; keys only in env vars; audit log is local, redacted and hash-chained; one-command memory wipe.
2. **Three risk levels**: SAFE runs; REVERSIBLE runs + undo entry; DANGEROUS (send, call, delete forever, shell, kill, download, install tool) needs a human yes issued by the interface.
3. **Taint tracking**: once untrusted content (web, email, file) is read in a turn, even reversible writes require confirmation - the main defence against prompt injection.
4. **Provider-agnostic JSON tool protocol**: works with small local models that lack native tool-calling.
5. **Extensible**: plugins (`~/.vaelon/plugins`), hooks (`~/.vaelon/hooks`), skills (`~/.vaelon/skills`), sub-agents.
