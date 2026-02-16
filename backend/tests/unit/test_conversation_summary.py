"""Tests for backend.utils.conversation_summary."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from backend.utils.conversation_summary import (
    _generate_truncated_title,
    get_default_conversation_title,
    generate_conversation_title,
)


# ── _generate_truncated_title ────────────────────────────────────────

class TestGenerateTruncatedTitle:
    def test_short_message(self):
        assert _generate_truncated_title("hello") == "hello"

    def test_long_message(self):
        msg = "x" * 50
        title = _generate_truncated_title(msg, max_length=30)
        assert len(title) <= 33  # 30 + "..."
        assert title.endswith("...")

    def test_exact_length(self):
        msg = "a" * 30
        title = _generate_truncated_title(msg, max_length=30)
        assert title == msg  # no ellipsis

    def test_strips_whitespace(self):
        title = _generate_truncated_title("  hello  ", max_length=30)
        assert title == "hello"


# ── get_default_conversation_title ───────────────────────────────────

class TestGetDefaultTitle:
    def test_basic(self):
        title = get_default_conversation_title("abc12345")
        assert title == "Conversation abc12"

    def test_short_id(self):
        title = get_default_conversation_title("ab")
        assert title.startswith("Conversation")


# ── generate_conversation_title ──────────────────────────────────────

class TestGenerateConversationTitle:
    @pytest.mark.asyncio
    async def test_empty_message(self):
        result = await generate_conversation_title("", MagicMock(), MagicMock())
        assert result is None

    @pytest.mark.asyncio
    async def test_whitespace_only(self):
        result = await generate_conversation_title("   ", MagicMock(), MagicMock())
        assert result is None

    @pytest.mark.asyncio
    async def test_success(self):
        registry = MagicMock()
        registry.request_extraneous_completion.return_value = "My Title"
        result = await generate_conversation_title(
            "hello world", MagicMock(), registry
        )
        assert result == "My Title"

    @pytest.mark.asyncio
    async def test_truncates_long_title(self):
        registry = MagicMock()
        registry.request_extraneous_completion.return_value = "x" * 100
        result = await generate_conversation_title(
            "hello world", MagicMock(), registry, max_length=20
        )
        assert len(result) <= 20
        assert result.endswith("...")

    @pytest.mark.asyncio
    async def test_llm_error_returns_none(self):
        registry = MagicMock()
        registry.request_extraneous_completion.side_effect = RuntimeError("fail")
        result = await generate_conversation_title(
            "hello world", MagicMock(), registry
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_long_message_truncated(self):
        long_msg = "a" * 2000
        registry = MagicMock()
        registry.request_extraneous_completion.return_value = "Title"
        result = await generate_conversation_title(
            long_msg, MagicMock(), registry
        )
        # Should pass truncated message to LLM
        call_args = registry.request_extraneous_completion.call_args
        messages = call_args[0][2]  # third positional arg
        user_content = messages[1]["content"]
        assert "truncated" in user_content
