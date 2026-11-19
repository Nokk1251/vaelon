"""A tool context for calls the owner makes from the app (not from the model): no approver needed, nothing tainted."""
from __future__ import annotations


def ctx_for(cfg):
    from .tools import registry

    registry.load_builtin()
    return registry.Ctx(cfg)
