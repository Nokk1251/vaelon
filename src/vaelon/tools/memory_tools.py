"""Memory + undo tools."""
from __future__ import annotations

from ..security import undo as undo_mod
from .registry import tool


@tool("remember", "Store a durable fact/preference about the user", {"text": "what to remember"}, group="memory")
def remember(ctx, text):
    return f"remembered (id {ctx.memory.add(text)})"


@tool("recall", "Search long-term memory", {"query": "keywords"}, group="memory")
def recall(ctx, query):
    rows = ctx.memory.search(query)
    return "\n".join(f"#{i}: {t}" for i, t in rows) or "nothing found"


@tool("forget", "Delete a memory by id", {"id": "memory id"}, group="memory")
def forget(ctx, id):
    return "forgotten" if ctx.memory.forget(int(id)) else "no such id"


@tool("undo", "Undo the user's last reversible action (file write/move/delete)", group="memory")
def undo(ctx):
    return undo_mod.undo()
