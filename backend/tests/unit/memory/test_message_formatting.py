"""Tests for backend.memory.message_formatting — message utilities and type checks."""

from __future__ import annotations

from unittest.mock import MagicMock


from backend.core.message import Message, TextContent, ImageContent
from backend.events.action import MessageAction
from backend.events.observation import Observation
from backend.memory.message_formatting import (
    apply_user_message_formatting,
    class_name_in_mro,
    extract_first_text,
    is_action_event,
    is_instance_of,
    is_message_action,
    is_observation_event,
    is_text_content,
    message_with_text,
    remove_duplicate_system_prompt_user,
)


class TestClassNameInMro:
    """Tests for class_name_in_mro function."""

    def test_finds_class_in_mro(self):
        """Test finds target class name in MRO chain."""

        class Base:
            pass

        class Derived(Base):
            pass

        obj = Derived()
        assert class_name_in_mro(obj, "Base") is True
        assert class_name_in_mro(obj, "Derived") is True

    def test_returns_false_for_missing_class(self):
        """Test returns False when class not in MRO."""

        class MyClass:
            pass

        obj = MyClass()
        assert class_name_in_mro(obj, "NonExistent") is False

    def test_works_with_class_objects(self):
        """Test works when passed a class instead of instance."""

        class MyClass:
            pass

        assert class_name_in_mro(MyClass, "MyClass") is True

    def test_returns_false_for_none_target(self):
        """Test returns False when target_name is None."""
        assert class_name_in_mro("anything", None) is False

    def test_returns_false_for_none_obj(self):
        """Test returns False when obj is None."""
        assert class_name_in_mro(None, "SomeClass") is False


class TestIsInstanceOf:
    """Tests for is_instance_of function."""

    def test_detects_normal_instance(self):
        """Test detects normal isinstance relationship."""
        assert is_instance_of("hello", str) is True
        assert is_instance_of(42, int) is True
        assert is_instance_of([], list) is True

    def test_detects_subclass_instance(self):
        """Test detects subclass instances."""

        class Base:
            pass

        class Derived(Base):
            pass

        obj = Derived()
        assert is_instance_of(obj, Base) is True
        assert is_instance_of(obj, Derived) is True

    def test_returns_false_for_wrong_type(self):
        """Test returns False when types don't match."""
        assert is_instance_of("hello", int) is False
        assert is_instance_of(42, str) is False

    def test_resilient_to_module_reloads(self):
        """Test uses duck typing when isinstance fails but name matches."""

        # Create a custom class with Message in its name
        class Message_Duplicate:
            pass

        obj = Message_Duplicate()
        # Should match by class name even though it's not the real Message
        assert class_name_in_mro(obj, "Message_Duplicate") is True


class TestIsTextContent:
    """Tests for is_text_content function."""

    def test_detects_real_text_content(self):
        """Test detects actual TextContent instances."""
        content = TextContent(text="Hello world")
        assert is_text_content(content) is True

    def test_detects_duck_typed_text_content(self):
        """Test detects objects with text content duck typing."""
        mock = MagicMock()
        mock.type = "text"
        mock.text = "Some text"

        assert is_text_content(mock) is True

    def test_rejects_non_text_content(self):
        """Test returns False for non-text content."""
        mock = MagicMock()
        mock.type = "image"
        mock.data = b"bytes"

        assert is_text_content(mock) is False

    def test_rejects_missing_attributes(self):
        """Test returns False when required attributes missing."""

        # Create object with type but without text
        class FakeContent:
            type = "text"
            # No text attribute

        assert is_text_content(FakeContent()) is False


class TestIsActionEvent:
    """Tests for is_action_event function."""

    def test_detects_message_action(self):
        """Test detects MessageAction as an action."""

        action = MessageAction(content="test message")
        assert is_action_event(action) is True

    def test_rejects_non_action(self):
        """Test returns False for non-action objects."""
        assert is_action_event("not an action") is False
        assert is_action_event(42) is False


class TestIsObservationEvent:
    """Tests for is_observation_event function."""

    def test_detects_observation(self):
        """Test detects Observation instances."""
        obs = Observation(content="test observation")
        assert is_observation_event(obs) is True

    def test_rejects_non_observation(self):
        """Test returns False for non-observation objects."""
        assert is_observation_event("not an observation") is False
        assert is_observation_event([]) is False


class TestIsMessageAction:
    """Tests for is_message_action function."""

    def test_detects_message_action(self):
        """Test detects MessageAction instances."""
        action = MessageAction(content="assistant message")
        assert is_message_action(action) is True

    def test_rejects_non_message_action(self):
        """Test returns False for non-MessageAction objects."""
        assert is_message_action("not a message action") is False
        assert is_message_action({}) is False


class TestExtractFirstText:
    """Tests for extract_first_text function."""

    def test_extracts_text_from_message(self):
        """Test extracts text from first TextContent item."""
        msg = Message(
            role="user",
            content=[TextContent(text="First text"), TextContent(text="Second text")],
        )
        assert extract_first_text(msg) == "First text"

    def test_returns_none_for_empty_content(self):
        """Test returns None when message has no content."""
        msg = Message(role="user", content=[])
        assert extract_first_text(msg) is None

    def test_returns_none_for_none_message(self):
        """Test returns None when message is None."""
        assert extract_first_text(None) is None

    def test_skips_non_text_content(self):
        """Test skips non-text content items to find text."""
        msg = Message(
            role="user",
            content=[
                ImageContent(image_urls=["http://example.com/img.png"]),
                TextContent(text="Found text"),
            ],
        )
        assert extract_first_text(msg) == "Found text"

    def test_returns_none_when_no_text_content(self):
        """Test returns None when no TextContent items exist."""
        msg = Message(
            role="user",
            content=[ImageContent(image_urls=["http://example.com/img.png"])],
        )
        assert extract_first_text(msg) is None


class TestMessageWithText:
    """Tests for message_with_text function."""

    def test_creates_message_with_text_content(self):
        """Test creates Message with single TextContent."""
        msg = message_with_text("assistant", "Hello world")

        assert msg.role == "assistant"
        assert len(msg.content) == 1
        assert isinstance(msg.content[0], TextContent)
        assert msg.content[0].text == "Hello world"

    def test_handles_empty_text(self):
        """Test creates message with empty text."""
        msg = message_with_text("user", "")

        assert msg.role == "user"
        assert msg.content[0].text == ""


class TestRemoveDuplicateSystemPromptUser:
    """Tests for remove_duplicate_system_prompt_user function."""

    def test_removes_duplicate_user_message(self):
        """Test removes user message that duplicates system prompt."""
        messages = [
            Message(role="system", content=[TextContent(text="System prompt")]),
            Message(role="user", content=[TextContent(text="System prompt")]),
            Message(role="assistant", content=[TextContent(text="Response")]),
        ]

        result = remove_duplicate_system_prompt_user(messages)

        assert len(result) == 2
        assert result[0].role == "system"
        assert result[1].role == "assistant"

    def test_preserves_non_duplicate_user_message(self):
        """Test preserves user message when it doesn't duplicate system."""
        messages = [
            Message(role="system", content=[TextContent(text="System prompt")]),
            Message(role="user", content=[TextContent(text="Different text")]),
        ]

        result = remove_duplicate_system_prompt_user(messages)

        assert len(result) == 2
        assert result[1].role == "user"

    def test_handles_short_message_lists(self):
        """Test returns input unchanged when fewer than 2 messages."""
        single = [Message(role="system", content=[TextContent(text="Only one")])]
        assert remove_duplicate_system_prompt_user(single) == single

        empty: list[Message] = []
        assert remove_duplicate_system_prompt_user(empty) == empty

    def test_ignores_whitespace_differences(self):
        """Test removes duplicate even with whitespace differences."""
        messages = [
            Message(role="system", content=[TextContent(text="  System prompt  ")]),
            Message(
                role="user", content=[TextContent(text="System prompt")]
            ),  # No extra whitespace
        ]

        result = remove_duplicate_system_prompt_user(messages)

        # Should detect as duplicate despite whitespace
        assert len(result) == 1

    def test_preserves_when_first_is_not_system(self):
        """Test preserves structure when first message is not system."""
        messages = [
            Message(role="user", content=[TextContent(text="Hello")]),
            Message(role="assistant", content=[TextContent(text="Hi")]),
        ]

        result = remove_duplicate_system_prompt_user(messages)

        assert result == messages


class TestApplyUserMessageFormatting:
    """Tests for apply_user_message_formatting function."""

    def test_adds_newlines_between_consecutive_user_messages(self):
        """Test adds \\n\\n prefix to consecutive user messages."""
        messages = [
            Message(role="user", content=[TextContent(text="First user message")]),
            Message(role="user", content=[TextContent(text="Second user message")]),
        ]

        result = apply_user_message_formatting(messages)

        assert result[0].content[0].text == "First user message"
        assert result[1].content[0].text == "\n\nSecond user message"

    def test_preserves_non_consecutive_user_messages(self):
        """Test doesn't add newlines when user messages aren't consecutive."""
        messages = [
            Message(role="user", content=[TextContent(text="User 1")]),
            Message(role="assistant", content=[TextContent(text="Assistant")]),
            Message(role="user", content=[TextContent(text="User 2")]),
        ]

        result = apply_user_message_formatting(messages)

        assert result[0].content[0].text == "User 1"
        assert result[2].content[0].text == "User 2"  # No \n\n prefix

    def test_skips_empty_content_messages(self):
        """Test handles messages with empty content gracefully."""
        messages = [
            Message(role="user", content=[TextContent(text="First")]),
            Message(role="user", content=[]),  # Empty
        ]

        result = apply_user_message_formatting(messages)

        # Should not crash
        assert len(result) == 2

    def test_creates_deep_copies_of_messages(self):
        """Test creates deep copies so original messages aren't mutated."""
        original_text = "Original"
        messages = [
            Message(role="user", content=[TextContent(text=original_text)]),
            Message(role="user", content=[TextContent(text="Second")]),
        ]

        result = apply_user_message_formatting(messages)

        # Original should be unchanged
        assert messages[1].content[0].text == "Second"
        # Result should have modification
        assert result[1].content[0].text == "\n\nSecond"

    def test_handles_multiple_consecutive_user_messages(self):
        """Test handles chain of 3+ consecutive user messages."""
        messages = [
            Message(role="user", content=[TextContent(text="First")]),
            Message(role="user", content=[TextContent(text="Second")]),
            Message(role="user", content=[TextContent(text="Third")]),
        ]

        result = apply_user_message_formatting(messages)

        assert result[0].content[0].text == "First"
        assert result[1].content[0].text == "\n\nSecond"
        assert result[2].content[0].text == "\n\nThird"

    def test_preserves_existing_newlines(self):
        """Test doesn't add newlines when text already starts with \\n\\n."""
        messages = [
            Message(role="user", content=[TextContent(text="First")]),
            Message(role="user", content=[TextContent(text="\n\nAlready formatted")]),
        ]

        result = apply_user_message_formatting(messages)

        # Should not add additional \n\n
        assert result[1].content[0].text == "\n\nAlready formatted"

    def test_handles_non_text_content(self):
        """Test skips non-text content items."""
        messages = [
            Message(role="user", content=[TextContent(text="First")]),
            Message(
                role="user",
                content=[ImageContent(image_urls=["http://example.com/img.png"])],
            ),
        ]

        result = apply_user_message_formatting(messages)

        # Should not crash
        assert len(result) == 2
