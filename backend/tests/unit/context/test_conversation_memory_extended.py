"""Tests for ConversationMemory – pure helper methods and formatting logic."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from typing import cast


from backend.core.message import ImageContent, Message, TextContent
from backend.core.config import AgentConfig
from backend.context.conversation_memory import ConversationMemory
from backend.context.memory_types import DecisionType
from backend.context.message_formatting import (
    apply_user_message_formatting,
    class_name_in_mro,
    extract_first_text,
    is_text_content,
    message_with_text,
    remove_duplicate_system_prompt_user,
)


def _make_config(**overrides) -> SimpleNamespace:
    defaults = {
        "enable_vector_memory": False,
        "enable_som_visual_browsing": False,
        "enable_hybrid_retrieval": False,
        "cli_mode": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_memory(**config_kw) -> ConversationMemory:
    cfg = _make_config(**config_kw)
    pm = MagicMock()
    pm.get_system_message.return_value = "System prompt"
    return ConversationMemory(cast(AgentConfig, cfg), pm)


# ── _is_valid_image_url ─────────────────────────────────────────────


class TestIsValidImageUrl:
    def test_valid_url(self):
        assert (
            ConversationMemory._is_valid_image_url("https://example.com/img.png")
            is True
        )

    def test_none(self):
        assert ConversationMemory._is_valid_image_url(None) is False

    def test_empty(self):
        assert ConversationMemory._is_valid_image_url("") is False

    def test_whitespace(self):
        assert ConversationMemory._is_valid_image_url("   ") is False


# ── _message_with_text ───────────────────────────────────────────────


class TestMessageWithText:
    def test_creates_user_message(self):
        msg = message_with_text("user", "hello")
        assert msg.role == "user"
        assert len(msg.content) == 1
        c = msg.content[0]
        assert isinstance(c, TextContent) and c.text == "hello"

    def test_creates_system_message(self):
        msg = message_with_text("system", "sys prompt")
        assert msg.role == "system"


# ── _is_text_content ─────────────────────────────────────────────────


class TestIsTextContent:
    def test_real_text_content(self):
        tc = TextContent(text="hi")
        assert is_text_content(tc) is True

    def test_image_content(self):
        ic = ImageContent(image_urls=["http://example.com/img.png"])
        assert is_text_content(ic) is False

    def test_duck_typed(self):
        obj = SimpleNamespace(type="text", text="hello")
        assert is_text_content(obj) is True

    def test_non_text_duck(self):
        obj = SimpleNamespace(type="image", image_urls=[])
        assert is_text_content(obj) is False


# ── _class_name_in_mro ───────────────────────────────────────────────


class TestClassNameInMro:
    def test_exact_match(self):
        assert class_name_in_mro("hello", "str") is True

    def test_parent_match(self):
        assert class_name_in_mro(True, "int") is True

    def test_no_match(self):
        assert class_name_in_mro("hello", "int") is False

    def test_none_target(self):
        assert class_name_in_mro("hello", None) is False

    def test_none_obj(self):
        assert class_name_in_mro(None, "str") is False


# ── track_decision / add_anchor ──────────────────────────────────────


class TestDecisionsAndAnchors:
    def test_track_decision_returns_decision(self):
        mem = _make_memory()
        d = mem.track_decision(
            "use Python", "best fit", DecisionType.ARCHITECTURAL, "project"
        )
        assert d.description == "use Python"
        assert d.rationale == "best fit"
        assert d.decision_id in mem.decisions

    def test_add_anchor(self):
        mem = _make_memory()
        a = mem.add_anchor("critical config", "config", importance=0.95)
        assert a.content == "critical config"
        assert a.anchor_id in mem.anchors

    def test_get_context_summary_empty(self):
        mem = _make_memory()
        assert mem.get_context_summary() == ""

    def test_get_context_summary_with_data(self):
        mem = _make_memory()
        mem.add_anchor("important", "config")
        mem.track_decision("use Rust", "perf", DecisionType.TECHNICAL, "perf")
        summary = mem.get_context_summary()
        assert "Critical Context" in summary
        assert "Recent Decisions" in summary


# ── _apply_user_message_formatting ───────────────────────────────────


class TestUserMessageFormatting:
    def test_adds_separator_for_consecutive_user_messages(self):
        m1 = Message(role="user", content=[TextContent(text="first")])
        m2 = Message(role="user", content=[TextContent(text="second")])
        result = apply_user_message_formatting([m1, m2])
        c = result[1].content[0]
        assert isinstance(c, TextContent) and c.text.startswith("\n\n")

    def test_no_separator_for_mixed_roles(self):
        m1 = Message(role="user", content=[TextContent(text="first")])
        m2 = Message(role="assistant", content=[TextContent(text="reply")])
        m3 = Message(role="user", content=[TextContent(text="follow")])
        result = apply_user_message_formatting([m1, m2, m3])
        c = result[2].content[0]
        assert isinstance(c, TextContent) and not c.text.startswith("\n\n")

    def test_idempotent(self):
        m1 = Message(role="user", content=[TextContent(text="a")])
        m2 = Message(role="user", content=[TextContent(text="\n\nalready")])
        result = apply_user_message_formatting([m1, m2])
        c = result[1].content[0]
        assert isinstance(c, TextContent) and c.text == "\n\nalready"


# ── _remove_duplicate_system_prompt_user ─────────────────────────────


class TestRemoveDuplicateSystemUser:
    def test_removes_duplicate(self):
        sys_msg = Message(role="system", content=[TextContent(text="prompt")])
        dup_user = Message(role="user", content=[TextContent(text="prompt")])
        follow = Message(role="user", content=[TextContent(text="real")])
        result = remove_duplicate_system_prompt_user([sys_msg, dup_user, follow])
        assert len(result) == 2
        c = result[1].content[0]
        assert isinstance(c, TextContent) and c.text == "real"

    def test_keeps_non_duplicate(self):
        sys_msg = Message(role="system", content=[TextContent(text="prompt")])
        user_msg = Message(role="user", content=[TextContent(text="different")])
        result = remove_duplicate_system_prompt_user([sys_msg, user_msg])
        assert len(result) == 2


# ── _extract_first_text ──────────────────────────────────────────────


class TestExtractFirstText:
    def test_extracts(self):
        msg = Message(role="user", content=[TextContent(text="hello")])
        assert extract_first_text(msg) == "hello"

    def test_none_message(self):
        assert extract_first_text(None) is None

    def test_no_content(self):
        msg = Message(role="user", content=[])
        assert extract_first_text(msg) is None


class TestStoreRecallNoVector:
    def test_store_noop(self):
        mem = _make_memory()
        mem.store_in_memory("e1", "user", "hello")  # should not error

    def test_recall_returns_empty(self):
        mem = _make_memory()
        result = mem.recall_from_memory("query")
        assert result == []
