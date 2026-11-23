# Third-party notices and inspiration

All code in this repository was written for Vaelon and is licensed under GPL-3.0-or-later with the
attribution terms in NOTICE (see LICENSE and NOTICE). Until 2026-11-09 it was unpublished and marked Apache-2.0;
the sole author relicensed it before the first public release.

No source code from other projects is included. Ideas that inspired the design (not code):
- OpenJarvis (Apache-2.0): tool registry, capability/risk policy, guardrails, SSRF guard, channels, CLI layout
- isair/jarvis: privacy-first principles, fencing untrusted web content, wake-word-then-process
- Priler/jarvis: fully offline voice path
- AbuZar-Ansarii/Ultron: persona, unforgeable confirmation, undo stack, self-written tools
- modelscope/ultron (Apache-2.0): SKILL.md format, memory -> skill crystallisation
- microsoft/JARVIS (MIT): LLM-as-controller planning, delegation to specialist agents
- sagar-builds/ultron (MIT): an earlier version of the web UI was derived from its orb; that code was
  fully replaced in v0.2 by the original Swarm interface (ui/web)

The MCP client (`src/vaelon/mcp.py`) was written from the public Model Context Protocol specification
(modelcontextprotocol.io); no SDK or other implementation was used or copied.

Runtime dependencies keep their own licenses (requests, three.js, Next.js, React, react-markdown and
remark-gfm (MIT), python-docx, openpyxl and python-pptx (MIT), websockets (BSD-3-Clause), fpdf2 (LGPL-3.0), pypdf (BSD-3-Clause), Pillow (MIT-CMU), tzdata on Windows (Apache-2.0), Piper voices, etc.). piper-tts is GPL-3.0-or-later, which is compatible with Vaelon's own GPL-3.0-or-later license.
Piper voice models (bg_BG-dimitar, en_GB-alan) are downloaded by `vaelon voice-setup`; see their MODEL_CARD files.

Vaelon is an original name. Earlier private builds used a working title; the project was renamed before its
first public release. Not affiliated with any film studio, publisher or other software project.
