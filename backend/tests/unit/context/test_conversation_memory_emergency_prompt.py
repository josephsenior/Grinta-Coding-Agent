"""Focused tests for emergency system prompt fallback in ContextMemory."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.context.conversation_memory import ContextMemory


def _make_memory() -> ContextMemory:
    config = SimpleNamespace(
        enable_vector_memory=False,
        enable_som_visual_browsing=False,
        enable_hybrid_retrieval=False,
        cli_mode=False,
    )
    prompt_manager = MagicMock()
    prompt_manager.get_system_message.side_effect = RuntimeError("boom")
    return ContextMemory(config, prompt_manager)


class TestEmergencySystemPrompt:
    def test_raises_without_app_emergency_toggle(self, monkeypatch):
        memory = _make_memory()
        monkeypatch.delenv("APP_ALLOW_EMERGENCY_SYSTEM_PROMPT", raising=False)

        with pytest.raises(RuntimeError, match="APP_ALLOW_EMERGENCY_SYSTEM_PROMPT=1"):
            memory._ensure_leading_system_message([])

    def test_allows_minimal_prompt_with_app_emergency_toggle(self, monkeypatch):
        memory = _make_memory()
        monkeypatch.setenv("APP_ALLOW_EMERGENCY_SYSTEM_PROMPT", "1")

        messages = memory._ensure_leading_system_message([])

        assert len(messages) == 1
        assert messages[0].role == "system"