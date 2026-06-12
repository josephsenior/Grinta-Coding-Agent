"""Persistence and retrieval primitives for Grinta conversational memory."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

# Lazy imports to avoid heavy dependencies at package-level import.

if TYPE_CHECKING:
    from backend.context.agent_memory import Memory
    from backend.context.conversation_memory import ContextMemory


def __getattr__(name: str) -> Any:
    if name == 'Memory':
        from backend.context.agent_memory import Memory

        return Memory
    if name == 'ContextMemory':
        from backend.context.conversation_memory import ContextMemory

        return ContextMemory
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


__all__ = ['Memory', 'ContextMemory']
