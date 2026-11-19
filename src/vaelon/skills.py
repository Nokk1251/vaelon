"""Skills: SKILL.md-style markdown playbooks (frontmatter: name, description, triggers).

Loaded from the package (data/skills) and ~/.vaelon/skills. The best matches are injected into the prompt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import config


@dataclass
class Skill:
    name: str
    description: str
    triggers: list
    body: str


def parse(text: str) -> Skill | None:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        return None
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    if "name" not in meta:
        return None
    trig = [t.strip().lower() for t in meta.get("triggers", "").split(",") if t.strip()]
    return Skill(meta["name"], meta.get("description", ""), trig, m.group(2).strip())


def load_all() -> list[Skill]:
    dirs = [Path(__file__).parent / "data" / "skills", config.HOME / "skills"]
    out = []
    for d in dirs:
        if d.is_dir():
            for f in sorted(d.glob("*.md")):
                s = parse(f.read_text("utf-8"))
                if s:
                    out.append(s)
    return out


def match(request: str, skills: list[Skill], top: int = 2) -> list[Skill]:
    """A trigger must start at a word boundary: 'call' matches "call mum" but not "recall"; Bulgarian endings
    still match ('науча' -> 'научавам')."""
    q = request.lower()
    scored = [(sum(1 for t in s.triggers if re.search(r"(?<!\w)" + re.escape(t), q)), s) for s in skills]
    return [s for n, s in sorted(scored, key=lambda x: -x[0]) if n > 0][:top]
