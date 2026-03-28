"""Unit tests for backend.inference.debug_mixin."""

from __future__ import annotations

from typing import Any, cast
from unittest import TestCase
from unittest.mock import MagicMock, patch

from backend.inference.debug_mixin import MESSAGE_SEPARATOR, DebugMixin


class TestDebugMixin(TestCase):
    """Test DebugMixin class."""

    def setUp(self):
        """Set up test fixtures."""

        # Create a concrete implementation of DebugMixin for testing
        class ConcreteDebugMixin(DebugMixin):
            def vision_is_active(self) -> bool:
                return False

        self.mixin = ConcreteDebugMixin(debug=True)

    def test_initialization_with_debug_true(self):
        """Test initialization with debug=True."""
        mixin = DebugMixin(debug=True)
        self.assertTrue(mixin.debug)

    def test_initialization_with_debug_false(self):
        """Test initialization with debug=False."""
        mixin = DebugMixin(debug=False)
        self.assertFalse(mixin.debug)

    def test_initialization_default_debug(self):
        """Test initialization with default debug value."""
        mixin = DebugMixin()
        self.assertFalse(mixin.debug)

    def test_message_separator_constant(self):
        """Test MESSAGE_SEPARATOR constant value."""
        self.assertEqual(MESSAGE_SEPARATOR, "\n\n----------\n\n")

    @patch("backend.inference.debug_mixin.logger")
    @patch("backend.inference.debug_mixin.llm_prompt_logger")
    def test_log_prompt_single_message(self, mock_prompt_logger, mock_logger):
        """Test logging a single prompt message."""
        mock_logger.isEnabledFor.return_value = True

        message = {"role": "user", "content": "Hello, world!"}
        self.mixin.log_prompt([message])

        mock_prompt_logger.debug.assert_called_once_with("Hello, world!")

    @patch("backend.inference.debug_mixin.logger")
    @patch("backend.inference.debug_mixin.llm_prompt_logger")
    def test_log_prompt_multiple_messages(self, mock_prompt_logger, mock_logger):
        """Test logging multiple prompt messages."""
        mock_logger.isEnabledFor.return_value = True

        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello!"},
        ]
        self.mixin.log_prompt(messages)

        expected = "You are a helpful assistant.\n\n----------\n\nHello!"
        mock_prompt_logger.debug.assert_called_once_with(expected)

    @patch("backend.inference.debug_mixin.logger")
    def test_log_prompt_single_dict(self, mock_logger):
        """Test logging a single message dict (not in a list)."""
        mock_logger.isEnabledFor.return_value = True

        message = {"role": "user", "content": "Single message"}
        with patch("backend.inference.debug_mixin.llm_prompt_logger") as mock_prompt_logger:
            self.mixin.log_prompt(message)
            mock_prompt_logger.debug.assert_called_once_with("Single message")

    @patch("backend.inference.debug_mixin.logger")
    def test_log_prompt_empty_messages(self, mock_logger):
        """Test logging empty messages."""
        mock_logger.isEnabledFor.return_value = True

        self.mixin.log_prompt([])

        mock_logger.debug.assert_called_once_with("No completion messages!")

    @patch("backend.inference.debug_mixin.logger")
    def test_log_prompt_none_messages(self, mock_logger):
        """Test logging None messages."""
        mock_logger.isEnabledFor.return_value = True

        self.mixin.log_prompt(cast(Any, None))

        mock_logger.debug.assert_called_once_with("No completion messages!")

    @patch("backend.inference.debug_mixin.logger")
    def test_log_prompt_messages_without_content(self, mock_logger):
        """Test logging messages without content field."""
        mock_logger.isEnabledFor.return_value = True

        messages: list[dict[str, Any]] = [
            {"role": "user", "content": cast(Any, None)},
            {"role": "assistant"},  # No content field
        ]
        self.mixin.log_prompt(messages)

        mock_logger.debug.assert_called_once_with("No completion messages!")

    @patch("backend.inference.debug_mixin.logger")
    def test_log_prompt_debug_disabled(self, mock_logger):
        """Test log_prompt when debug logging is disabled."""
        mock_logger.isEnabledFor.return_value = False

        message = {"role": "user", "content": "Test"}
        with patch("backend.inference.debug_mixin.llm_prompt_logger") as mock_prompt_logger:
            self.mixin.log_prompt([message])
            mock_prompt_logger.debug.assert_not_called()

    @patch("backend.inference.debug_mixin.logger")
    @patch("backend.inference.debug_mixin.llm_response_logger")
    def test_log_response_string(self, mock_response_logger, mock_logger):
        """Test logging response as string."""
        mock_logger.isEnabledFor.return_value = True

        self.mixin.log_response("Hello from the model!")

        mock_response_logger.debug.assert_called_once_with("Hello from the model!")

    @patch("backend.inference.debug_mixin.logger")
    @patch("backend.inference.debug_mixin.llm_response_logger")
    def test_log_response_empty_string(self, mock_response_logger, mock_logger):
        """Test logging empty string response."""
        mock_logger.isEnabledFor.return_value = True

        self.mixin.log_response("")

        mock_response_logger.debug.assert_not_called()

    @patch("backend.inference.debug_mixin.logger")
    @patch("backend.inference.debug_mixin.llm_response_logger")
    def test_log_response_dict_with_content(self, mock_response_logger, mock_logger):
        """Test logging response dict with message content."""
        mock_logger.isEnabledFor.return_value = True

        response = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "This is the response.",
                    }
                }
            ]
        }
        self.mixin.log_response(response)

        mock_response_logger.debug.assert_called_once_with("This is the response.")

    @patch("backend.inference.debug_mixin.logger")
    @patch("backend.inference.debug_mixin.llm_response_logger")
    def test_log_response_dict_with_tool_calls(self, mock_response_logger, mock_logger):
        """Test logging response dict with tool calls."""
        mock_logger.isEnabledFor.return_value = True

        response = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Using a tool.",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"location": "NYC"}',
                                }
                            }
                        ],
                    }
                }
            ]
        }
        self.mixin.log_response(response)

        expected = 'Using a tool.\nFunction call: get_weather({"location": "NYC"})'
        mock_response_logger.debug.assert_called_once_with(expected)

    @patch("backend.inference.debug_mixin.logger")
    @patch("backend.inference.debug_mixin.llm_response_logger")
    def test_log_response_dict_with_object_style_tool_calls(
        self, mock_response_logger, mock_logger
    ):
        """Test logging response dict with object-style tool calls."""
        mock_logger.isEnabledFor.return_value = True

        # Create mock object-style tool call
        tool_call = MagicMock()
        tool_call.function.name = "calculate"
        tool_call.function.arguments = '{"a": 5, "b": 3}'

        response = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [tool_call],
                    }
                }
            ]
        }
        self.mixin.log_response(response)

        expected = '\nFunction call: calculate({"a": 5, "b": 3})'
        mock_response_logger.debug.assert_called_once_with(expected)

    @patch("backend.inference.debug_mixin.logger")
    @patch("backend.inference.debug_mixin.llm_response_logger")
    def test_log_response_dict_without_choices(self, mock_response_logger, mock_logger):
        """Test logging response dict without choices field."""
        mock_logger.isEnabledFor.return_value = True

        response = {"id": "123", "model": "gpt-4"}
        self.mixin.log_response(response)

        mock_response_logger.debug.assert_not_called()

    @patch("backend.inference.debug_mixin.logger")
    def test_log_response_debug_disabled(self, mock_logger):
        """Test log_response when debug logging is disabled."""
        mock_logger.isEnabledFor.return_value = False

        with patch(
            "backend.inference.debug_mixin.llm_response_logger"
        ) as mock_response_logger:
            self.mixin.log_response("Test response")
            mock_response_logger.debug.assert_not_called()

    def test_format_message_content_string(self):
        """Test formatting message content as string."""
        message = {"content": "Simple text"}
        result = self.mixin._format_message_content(message)
        self.assertEqual(result, "Simple text")

    def test_format_message_content_list(self):
        """Test formatting message content as list."""
        message = {
            "content": [
                {"text": "Hello "},
                {"text": "world"},
            ]
        }
        result = self.mixin._format_message_content(message)
        self.assertEqual(result, "Hello \nworld")

    def test_format_message_content_mixed_types(self):
        """Test formatting message content with mixed types."""
        message = {
            "content": [
                {"text": "Text part"},
                "String part",
                123,
            ]
        }
        result = self.mixin._format_message_content(message)
        self.assertEqual(result, "Text part\nString part\n123")

    def test_format_content_element_text(self):
        """Test formatting content element with text field."""
        element = {"text": "Hello"}
        result = self.mixin._format_content_element(element)
        self.assertEqual(result, "Hello")

    def test_format_content_element_non_dict(self):
        """Test formatting non-dict content element."""
        result = self.mixin._format_content_element("plain string")
        self.assertEqual(result, "plain string")

    def test_format_content_element_image_url_vision_inactive(self):
        """Test formatting image_url element when vision is inactive."""
        element = {"image_url": {"url": "https://example.com/image.jpg"}}
        result = self.mixin._format_content_element(element)
        # Should return string representation since vision is inactive
        self.assertIn("image_url", result)

    def test_format_content_element_image_url_vision_active(self):
        """Test formatting image_url element when vision is active."""

        class VisionActiveMixin(DebugMixin):
            def vision_is_active(self) -> bool:
                return True

        mixin = VisionActiveMixin(debug=True)
        element = {"image_url": {"url": "https://example.com/image.jpg"}}
        result = mixin._format_content_element(element)
        self.assertEqual(result, "https://example.com/image.jpg")

    def test_vision_is_active_not_implemented(self):
        """Test that vision_is_active raises NotImplementedError in base class."""
        mixin = DebugMixin(debug=True)
        with self.assertRaises(NotImplementedError):
            mixin.vision_is_active()

    @patch("backend.inference.debug_mixin.logger")
    @patch("backend.inference.debug_mixin.llm_prompt_logger")
    def test_log_prompt_preserves_message_order(self, mock_prompt_logger, mock_logger):
        """Test that log_prompt preserves message order."""
        mock_logger.isEnabledFor.return_value = True

        messages = [
            {"content": "First"},
            {"content": "Second"},
            {"content": "Third"},
        ]
        self.mixin.log_prompt(messages)

        expected = "First\n\n----------\n\nSecond\n\n----------\n\nThird"
        mock_prompt_logger.debug.assert_called_once_with(expected)

    @patch("backend.inference.debug_mixin.logger")
    @patch("backend.inference.debug_mixin.llm_response_logger")
    def test_log_response_multiple_tool_calls(self, mock_response_logger, mock_logger):
        """Test logging response with multiple tool calls."""
        mock_logger.isEnabledFor.return_value = True

        response = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "tool1",
                                    "arguments": '{"arg": "val1"}',
                                }
                            },
                            {
                                "function": {
                                    "name": "tool2",
                                    "arguments": '{"arg": "val2"}',
                                }
                            },
                        ],
                    }
                }
            ]
        }
        self.mixin.log_response(response)

        expected = '\nFunction call: tool1({"arg": "val1"})\nFunction call: tool2({"arg": "val2"})'
        mock_response_logger.debug.assert_called_once_with(expected)

    def test_debug_mixin_init_with_extra_args(self):
        """Test DebugMixin initialization accepts extra args/kwargs."""

        class ExtendedMixin(DebugMixin):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.extra = kwargs.get("extra", "default")

            def vision_is_active(self) -> bool:
                return False

        mixin = ExtendedMixin(debug=True, extra="value")
        self.assertTrue(mixin.debug)
        self.assertEqual(mixin.extra, "value")
