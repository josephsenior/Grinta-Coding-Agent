"""Tests for backend.utils.conversation_summary."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from typing import Any, cast

from backend.utils.conversation_summary import (
    _generate_truncated_title,
    get_default_conversation_title,
    generate_conversation_title,
    _get_first_user_message,
    _try_llm_title_generation,
    _auto_generate_title_impl,
)
from backend.events.event import EventSource


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
        result = await generate_conversation_title("hello world", MagicMock(), registry)
        assert result == "My Title"

    @pytest.mark.asyncio
    async def test_truncates_long_title(self):
        registry = MagicMock()
        registry.request_extraneous_completion.return_value = "x" * 100
        result = await generate_conversation_title(
            "hello world", MagicMock(), registry, max_length=20
        )
        assert result is not None
        assert len(result) <= 20
        assert result.endswith("...")

    @pytest.mark.asyncio
    async def test_llm_error_returns_none(self):
        registry = MagicMock()
        registry.request_extraneous_completion.side_effect = RuntimeError("fail")
        result = await generate_conversation_title("hello world", MagicMock(), registry)
        assert result is None

    @pytest.mark.asyncio
    async def test_long_message_truncated(self):
        long_msg = "a" * 2000
        registry = MagicMock()
        registry.request_extraneous_completion.return_value = "Title"
        await generate_conversation_title(long_msg, MagicMock(), registry)
        # Should pass truncated message to LLM
        call_args = registry.request_extraneous_completion.call_args
        messages = call_args[0][2]  # third positional arg
        user_content = messages[1]["content"]
        assert "truncated" in user_content


# ── _get_first_user_message ──────────────────────────────────────────


class TestGetFirstUserMessage:
    def test_gets_first_user_message(self):
        file_store = MagicMock()
        with patch("backend.utils.conversation_summary.EventStore") as MockEventStore:
            mock_event = MagicMock()
            mock_event.source = EventSource.USER
            mock_event.content = "My first message"

            MockEventStore.return_value.search_events.return_value = [mock_event]

            result = _get_first_user_message("conv-id", "user-id", file_store)
            assert result == "My first message"

    def test_ignores_non_user_messages(self):
        file_store = MagicMock()
        with patch("backend.utils.conversation_summary.EventStore") as MockEventStore:
            mock_event1 = MagicMock()
            mock_event1.source = EventSource.AGENT
            mock_event1.content = "Agent message"

            mock_event2 = MagicMock()
            mock_event2.source = EventSource.USER
            mock_event2.content = "User message"

            MockEventStore.return_value.search_events.return_value = [
                mock_event1,
                mock_event2,
            ]

            result = _get_first_user_message("conv-id", "user-id", file_store)
            assert result == "User message"

    def test_returns_none_if_no_user_message(self):
        file_store = MagicMock()
        with patch("backend.utils.conversation_summary.EventStore") as MockEventStore:
            MockEventStore.return_value.search_events.return_value = []

            result = _get_first_user_message("conv-id", "user-id", file_store)
            assert result is None


# ── _try_llm_title_generation ────────────────────────────────────────


class TestTryLlmTitleGeneration:
    @pytest.mark.asyncio
    async def test_no_model(self):
        settings = MagicMock()
        settings.llm_model = None
        result = await _try_llm_title_generation("message", settings, MagicMock())
        assert result is None

    @pytest.mark.asyncio
    async def test_success(self):
        settings = MagicMock()
        settings.llm_model = "gpt-4"
        settings.llm_api_key = "key"
        settings.llm_base_url = "url"

        registry = MagicMock()
        with patch(
            "backend.utils.conversation_summary.generate_conversation_title"
        ) as mock_gen:
            mock_gen.return_value = "LLM Title"
            result = await _try_llm_title_generation("message", settings, registry)
            assert result == "LLM Title"

    @pytest.mark.asyncio
    async def test_exception(self):
        settings = MagicMock()
        settings.llm_model = "gpt-4"
        registry = MagicMock()
        with patch(
            "backend.utils.conversation_summary.LLMConfig", side_effect=Exception("Oops")
        ):
            result = await _try_llm_title_generation("msg", settings, registry)
            assert result is None


# ── _auto_generate_title_impl ────────────────────────────────────────


class TestAutoGenerateTitleImpl:
    @pytest.mark.asyncio
    async def test_llm_success(self):
        with patch(
            "backend.utils.conversation_summary._get_first_user_message"
        ) as mock_get_msg, patch(
            "backend.utils.conversation_summary._try_llm_title_generation"
        ) as mock_try_llm:
            mock_get_msg.return_value = "Hello"
            mock_try_llm.return_value = "LLM Title"

            result = await _auto_generate_title_impl(
                "conv", "user", MagicMock(), MagicMock(), MagicMock()
            )
            assert result == "LLM Title"

    @pytest.mark.asyncio
    async def test_fallback_to_truncation(self):
        with patch(
            "backend.utils.conversation_summary._get_first_user_message"
        ) as mock_get_msg, patch(
            "backend.utils.conversation_summary._try_llm_title_generation"
        ) as mock_try_llm, patch(
            "backend.utils.conversation_summary._generate_truncated_title"
        ) as mock_truncate:
            mock_get_msg.return_value = "Long message"
            mock_try_llm.return_value = None
            mock_truncate.return_value = "Truncated"

            result = await _auto_generate_title_impl(
                "conv", "user", MagicMock(), MagicMock(), MagicMock()
            )
            assert result == "Truncated"

    @pytest.mark.asyncio
    async def test_no_first_message(self):
        with patch(
            "backend.utils.conversation_summary._get_first_user_message"
        ) as mock_get_msg:
            mock_get_msg.return_value = None
            file_store = MagicMock()
            file_store.list.return_value = []

            result = await _auto_generate_title_impl(
                "conv", "user", file_store, MagicMock(), MagicMock()
            )
            assert result == ""

    @pytest.mark.asyncio
    async def test_error_reading_message_dummy_store(self):
        with patch(
            "backend.utils.conversation_summary._get_first_user_message"
        ) as mock_get_msg:
            mock_get_msg.side_effect = Exception("Read error")
            file_store = object()  # dummy object lacks 'list'
            settings = MagicMock()
            settings.llm_model = "gpt-4"
            registry = MagicMock()

            # Should use benign seed 'Hello' and then try LLM
            with patch(
                "backend.utils.conversation_summary._try_llm_title_generation"
            ) as mock_try_llm:
                mock_try_llm.return_value = "LLM Seed Title"
                result = await _auto_generate_title_impl(
                    "conv", "user", cast(Any, file_store), settings, registry
                )
                assert result == "LLM Seed Title"
                mock_try_llm.assert_called_with("Hello", settings, registry)

    @pytest.mark.asyncio
    async def test_auto_generate_title_delegates(self):
        from backend.utils.conversation_summary import auto_generate_title

        file_store = MagicMock()
        settings = MagicMock()
        registry = MagicMock()
        # Note: the real auto_generate_title re-imports the module.
        # We need to patch the impl where it's actually called.
        with patch(
            "backend.utils.conversation_summary._auto_generate_title_impl"
        ) as mock_impl:
            mock_impl.return_value = "Delegated Title"
            result = await auto_generate_title(
                "conv", "user", file_store, settings, registry
            )
            assert result == "Delegated Title"

    @pytest.mark.asyncio
    async def test_error_reading_message_no_llm_model(self):
        with patch(
            "backend.utils.conversation_summary._get_first_user_message"
        ) as mock_get_msg:
            mock_get_msg.side_effect = Exception("Read error")
            file_store = object()  # no .list
            settings = (
                MagicMock()
            )  # By default it will have attributes, need to mock its lack
            del settings.llm_model
            result = await _auto_generate_title_impl(
                "conv", "user", cast(Any, file_store), settings, MagicMock()
            )
            assert result == ""

    @pytest.mark.asyncio
    async def test_error_reading_message_with_list(self):
        with patch(
            "backend.utils.conversation_summary._get_first_user_message"
        ) as mock_get_msg:
            mock_get_msg.side_effect = Exception("Read error")
            file_store = MagicMock()  # Has .list (as a Mock)
            result = await _auto_generate_title_impl(
                "conv", "user", file_store, MagicMock(), MagicMock()
            )
            assert result == ""

    @pytest.mark.asyncio
    async def test_llm_path_exception(self):
        with patch(
            "backend.utils.conversation_summary._get_first_user_message"
        ) as mock_get_msg, patch(
            "backend.utils.conversation_summary._try_llm_title_generation"
        ) as mock_try_llm:
            mock_get_msg.return_value = "Hello"
            mock_try_llm.side_effect = RuntimeError("LLM crash")

            result = await _auto_generate_title_impl(
                "conv", "user", MagicMock(), MagicMock(), MagicMock()
            )
            assert result == ""
