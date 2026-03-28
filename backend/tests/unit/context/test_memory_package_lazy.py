"""Tests for backend.context lazy package exports."""

from __future__ import annotations

import pytest


def test_lazy_memory_import() -> None:
    import backend.context as mem

    from backend.context.agent_memory import Memory as RealMemory

    assert mem.Memory is RealMemory


def test_lazy_conversation_memory_import() -> None:
    import backend.context as mem

    from backend.context.conversation_memory import ConversationMemory as RealCM

    assert mem.ConversationMemory is RealCM


def test_unknown_attribute_raises() -> None:
    import backend.context as mem

    with pytest.raises(AttributeError, match="not_a_symbol"):
        _ = mem.not_a_symbol  # type: ignore[attr-defined]
