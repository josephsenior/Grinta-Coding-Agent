"""Tests for backend.core.message — Message, Content, TextContent, ImageContent, ToolCall."""

from __future__ import annotations

import pytest

from backend.core.message import (
    Content,
    ImageContent,
    Message,
    TextContent,
    ToolCall,
    ToolCallFunction,
)


# ---------------------------------------------------------------------------
# ToolCallFunction / ToolCall
# ---------------------------------------------------------------------------

class TestToolCallFunction:
    """Tests for ToolCallFunction model."""

    def test_basic_creation(self):
        f = ToolCallFunction(name="my_func", arguments='{"key": "val"}')
        assert f.name == "my_func"
        assert f.arguments == '{"key": "val"}'


class TestToolCall:
    """Tests for ToolCall model."""

    def test_basic_creation(self):
        tc = ToolCall(
            id="call_123",
            function=ToolCallFunction(name="f", arguments="{}"),
        )
        assert tc.id == "call_123"
        assert tc.type == "function"
        assert tc.function.name == "f"

    def test_custom_type(self):
        tc = ToolCall(
            id="x", type="custom",
            function=ToolCallFunction(name="f", arguments="{}"),
        )
        assert tc.type == "custom"


# ---------------------------------------------------------------------------
# TextContent
# ---------------------------------------------------------------------------

class TestTextContent:
    """Tests for TextContent model."""

    def test_basic(self):
        tc = TextContent(text="hello")
        assert tc.text == "hello"
        assert tc.type == "text"
        assert tc.cache_prompt is False

    def test_serialization(self):
        tc = TextContent(text="hello")
        data = tc.serialize_model()
        assert data["type"] == "text"
        assert data["text"] == "hello"
        assert "cache_control" not in data

    def test_cache_prompt(self):
        tc = TextContent(text="hello", cache_prompt=True)
        data = tc.serialize_model()
        assert data["cache_control"] == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# ImageContent
# ---------------------------------------------------------------------------

class TestImageContent:
    """Tests for ImageContent model."""

    def test_basic(self):
        ic = ImageContent(image_urls=["http://img.com/1.png"])
        assert ic.image_urls == ["http://img.com/1.png"]

    def test_serialization(self):
        ic = ImageContent(image_urls=["http://a.com/1.png", "http://a.com/2.png"])
        data = ic.serialize_model()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["image_url"]["url"] == "http://a.com/1.png"

    def test_cache_prompt_on_last_image(self):
        ic = ImageContent(
            image_urls=["http://a.com/1.png", "http://a.com/2.png"],
            cache_prompt=True,
        )
        data = ic.serialize_model()
        assert "cache_control" not in data[0]
        assert data[1]["cache_control"] == {"type": "ephemeral"}

    def test_empty_images_no_crash(self):
        ic = ImageContent(image_urls=[])
        data = ic.serialize_model()
        assert data == []


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------

class TestMessage:
    """Tests for Message model."""

    def test_basic_user_message(self):
        msg = Message(role="user", content=[TextContent(text="hello")])
        assert msg.role == "user"
        assert len(msg.content) == 1

    def test_assistant_with_tool_calls(self):
        msg = Message(
            role="assistant",
            tool_calls=[
                ToolCall(id="c1", function=ToolCallFunction(name="f", arguments="{}")),
            ],
        )
        assert msg.tool_calls is not None
        assert len(msg.tool_calls) == 1

    def test_tool_response(self):
        msg = Message(role="tool", tool_call_id="c1", content=[TextContent(text="ok")])
        assert msg.tool_call_id == "c1"

    def test_defaults(self):
        msg = Message(role="system")
        assert msg.content == []
        assert msg.cache_enabled is False
        assert msg.vision_enabled is False
        assert msg.function_calling_enabled is False
        assert msg.tool_calls is None
        assert msg.tool_call_id is None
        assert msg.name is None

    def test_contains_text_and_image(self):
        msg = Message(
            role="user",
            content=[
                TextContent(text="Look at this"),
                ImageContent(image_urls=["http://img.com/x.png"]),
            ],
        )
        assert len(msg.content) == 2

    def test_force_string_serializer(self):
        msg = Message(role="user", force_string_serializer=True)
        assert msg.force_string_serializer is True
