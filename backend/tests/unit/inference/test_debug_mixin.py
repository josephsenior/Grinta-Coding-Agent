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

        class ConcreteDebugMixin(DebugMixin):
            def vision_is_active(self) -> bool:
                return False

        self.mixin = ConcreteDebugMixin(debug=True)

    def test_initialization_with_debug_true(self):
        mixin = DebugMixin(debug=True)
        self.assertTrue(mixin.debug)

    def test_initialization_with_debug_false(self):
        mixin = DebugMixin(debug=False)
        self.assertFalse(mixin.debug)

    def test_initialization_default_debug(self):
        mixin = DebugMixin()
        self.assertFalse(mixin.debug)

    def test_message_separator_constant(self):
        self.assertEqual(MESSAGE_SEPARATOR, '\n\n----------\n\n')

    @patch('backend.inference.debug_mixin.emit_session_event')
    def test_log_prompt_emits_wire_prompt(self, mock_emit):
        message = {'role': 'user', 'content': 'Hello, world!'}
        self.mixin.log_prompt([message])
        mock_emit.assert_called_once()
        assert mock_emit.call_args[0][0] == 'WIRE_PROMPT'
        payload = mock_emit.call_args[0][1]
        assert payload['messages'] == [message]

    @patch('backend.inference.debug_mixin.emit_session_event')
    def test_log_prompt_with_call_params(self, mock_emit):
        messages = [{'role': 'user', 'content': 'Hi'}]
        params = {'model': 'test/model', 'temperature': 0.7}
        self.mixin.log_prompt(messages, call_params=params)
        payload = mock_emit.call_args[0][1]
        assert payload['call_params'] == params

    @patch('backend.inference.debug_mixin.emit_session_event')
    def test_log_prompt_empty_skips(self, mock_emit):
        self.mixin.log_prompt([])
        mock_emit.assert_not_called()

    @patch('backend.inference.debug_mixin.emit_session_event')
    def test_log_response_string(self, mock_emit):
        self.mixin.log_response('Response text', latency_ms=100)
        mock_emit.assert_called_once()
        assert mock_emit.call_args[0][0] == 'WIRE_RESPONSE'
        payload = mock_emit.call_args[0][1]
        assert payload['content'] == 'Response text'
        assert payload['latency_ms'] == 100

    @patch('backend.inference.debug_mixin.emit_session_event')
    def test_log_response_dict_with_tool_calls(self, mock_emit):
        response = {
            'choices': [
                {
                    'message': {
                        'content': 'Calling tool',
                        'tool_calls': [
                            {
                                'function': {
                                    'name': 'read_file',
                                    'arguments': '{"path": "a.py"}',
                                }
                            }
                        ],
                    }
                }
            ]
        }
        self.mixin.log_response(response)
        payload = mock_emit.call_args[0][1]
        assert 'read_file' in payload.get('content', '')
        assert payload.get('tool_calls')

    @patch('backend.inference.debug_mixin.emit_session_event')
    def test_log_response_empty_string_skips(self, mock_emit):
        self.mixin.log_response('')
        mock_emit.assert_not_called()

    def test_format_message_content_string(self):
        msg = {'content': 'hello'}
        assert self.mixin._format_message_content(msg) == 'hello'

    def test_format_message_content_list(self):
        msg = {'content': [{'text': 'part1'}, {'text': 'part2'}]}
        result = self.mixin._format_message_content(msg)
        assert 'part1' in result
        assert 'part2' in result

    def test_vision_is_active_not_implemented(self):
        mixin = DebugMixin()
        with self.assertRaises(NotImplementedError):
            mixin.vision_is_active()
