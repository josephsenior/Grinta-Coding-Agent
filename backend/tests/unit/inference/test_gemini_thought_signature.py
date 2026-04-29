"""Tests for Gemini thought_signature extraction and replay.

Gemini 2.5 thinking models attach an opaque ``thought_signature`` (bytes) to
each function_call part.  The mapper must:

1. Extract the signature from the response (``extract_tool_calls``).
2. Re-emit it on the function_call part when replaying history
   (``convert_messages``), so the API does not reject the next turn.
"""

from __future__ import annotations

import json

from backend.inference.mappers.gemini import (
    _build_gemini_model_parts,
    _build_gemini_tool_response_parts,
    convert_messages,
    extract_tool_calls,
)


def _assert_text_history_part(entry: dict[str, object], *, role: str, text: str) -> None:
    assert entry['role'] == role
    part = entry['parts'][0]
    assert part['text'] == text


def _assert_function_call_history_part(
    entry: dict[str, object],
    *,
    role: str,
    name: str,
    args: dict[str, object],
    signature: bytes,
) -> None:
    assert entry['role'] == role
    part = entry['parts'][0]
    assert part['function_call']['name'] == name
    assert part['function_call']['args'] == args
    assert part['thought_signature'] == signature


def _assert_function_response_history_part(
    entry: dict[str, object],
    *,
    role: str,
    name: str,
    output: str,
) -> None:
    assert entry['role'] == role
    part = entry['parts'][0]
    assert part['function_response']['name'] == name
    assert part['function_response']['response']['output'] == output

# ---------------------------------------------------------------------------
# Stub objects mimicking google-genai SDK shape
# ---------------------------------------------------------------------------


class _StubFC:
    def __init__(self, name: str, args: dict) -> None:
        self.name = name
        self.args = args


class _StubPart:
    def __init__(
        self,
        function_call: _StubFC | None = None,
        text: str | None = None,
        thought_signature: bytes | None = None,
    ) -> None:
        self.function_call = function_call
        self.text = text
        self.thought_signature = thought_signature


class _StubContent:
    def __init__(self, parts: list[_StubPart]) -> None:
        self.parts = parts


class _StubCandidate:
    def __init__(self, parts: list[_StubPart]) -> None:
        self.content = _StubContent(parts)


class _StubResponse:
    def __init__(self, parts: list[_StubPart]) -> None:
        self.candidates = [_StubCandidate(parts)]


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


class TestExtractToolCallsThoughtSignature:
    def test_signature_is_extracted_when_present(self):
        sig = b'\x01\x02\x03opaque_blob'
        resp = _StubResponse(
            [
                _StubPart(
                    function_call=_StubFC('read_file', {'path': '/x'}),
                    thought_signature=sig,
                )
            ]
        )
        calls = extract_tool_calls(resp)
        assert calls is not None and len(calls) == 1
        assert calls[0]['thought_signature'] == sig

    def test_signature_absent_means_key_omitted(self):
        resp = _StubResponse(
            [_StubPart(function_call=_StubFC('read_file', {'path': '/x'}))]
        )
        calls = extract_tool_calls(resp)
        assert calls is not None and len(calls) == 1
        assert 'thought_signature' not in calls[0]

    def test_signature_round_trips_as_bytes(self):
        sig = b'\xff\x00\x10'
        resp = _StubResponse(
            [
                _StubPart(
                    function_call=_StubFC('grep', {'pattern': 'foo'}),
                    thought_signature=sig,
                )
            ]
        )
        calls = extract_tool_calls(resp)
        assert isinstance(calls[0]['thought_signature'], bytes)
        assert calls[0]['thought_signature'] == sig


# ---------------------------------------------------------------------------
# Parts-builder helpers
# ---------------------------------------------------------------------------


class TestBuildGeminiModelParts:
    def test_function_call_part_carries_signature(self):
        sig = b'sig123'
        parts = _build_gemini_model_parts(
            text='',
            tool_calls=[
                {
                    'id': 'gemini-0',
                    'type': 'function',
                    'function': {
                        'name': 'read_file',
                        'arguments': json.dumps({'path': '/x'}),
                    },
                    'thought_signature': sig,
                }
            ],
        )
        assert len(parts) == 1
        assert parts[0]['function_call'] == {
            'name': 'read_file',
            'args': {'path': '/x'},
        }
        assert parts[0]['thought_signature'] == sig

    def test_no_signature_means_no_signature_key(self):
        parts = _build_gemini_model_parts(
            text='',
            tool_calls=[
                {
                    'id': 'gemini-0',
                    'type': 'function',
                    'function': {
                        'name': 'read_file',
                        'arguments': '{}',
                    },
                }
            ],
        )
        assert 'thought_signature' not in parts[0]

    def test_leading_text_is_emitted_first(self):
        parts = _build_gemini_model_parts(
            text='Reading the file now.',
            tool_calls=[
                {
                    'function': {'name': 'read_file', 'arguments': '{}'},
                }
            ],
        )
        assert parts[0] == {'text': 'Reading the file now.'}
        assert 'function_call' in parts[1]


class TestBuildGeminiToolResponseParts:
    def test_simple_string_payload(self):
        parts = _build_gemini_tool_response_parts('read_file', 'file contents here')
        assert parts == [
            {
                'function_response': {
                    'name': 'read_file',
                    'response': {'output': 'file contents here'},
                }
            }
        ]

    def test_list_content_is_flattened_to_text(self):
        parts = _build_gemini_tool_response_parts(
            'read_file',
            [{'type': 'text', 'text': 'line1'}, {'type': 'text', 'text': 'line2'}],
        )
        assert parts[0]['function_response']['response']['output'] == 'line1\nline2'


# ---------------------------------------------------------------------------
# convert_messages: end-to-end replay
# ---------------------------------------------------------------------------


class TestConvertMessagesNativeToolHistory:
    def test_assistant_tool_calls_become_function_call_parts(self):
        sig = b'opaque'
        messages = [
            {'role': 'system', 'content': 'sys'},
            {'role': 'user', 'content': 'find foo'},
            {
                'role': 'assistant',
                'content': '',
                'tool_calls': [
                    {
                        'id': 'gemini-0',
                        'type': 'function',
                        'function': {
                            'name': 'grep',
                            'arguments': json.dumps({'pattern': 'foo'}),
                        },
                        'thought_signature': sig,
                    }
                ],
            },
            {
                'role': 'tool',
                'tool_call_id': 'gemini-0',
                'name': 'grep',
                'content': 'match: foo',
            },
            {'role': 'user', 'content': 'continue'},
        ]
        sysi, hist, _ = convert_messages(messages)

        assert sysi == 'sys'
        _assert_text_history_part(hist[0], role='user', text='find foo')
        _assert_function_call_history_part(
            hist[1],
            role='model',
            name='grep',
            args={'pattern': 'foo'},
            signature=sig,
        )
        _assert_function_response_history_part(
            hist[2],
            role='user',
            name='grep',
            output='match: foo',
        )
        _assert_text_history_part(hist[3], role='user', text='continue')

    def test_plain_text_messages_unchanged(self):
        messages = [
            {'role': 'user', 'content': 'hello'},
            {'role': 'assistant', 'content': 'hi'},
        ]
        _, hist, _ = convert_messages(messages)
        assert hist == [
            {'role': 'user', 'parts': [{'text': 'hello'}]},
            {'role': 'model', 'parts': [{'text': 'hi'}]},
        ]

    def test_assistant_without_tool_calls_uses_text_path(self):
        messages = [
            {'role': 'assistant', 'content': 'just text'},
        ]
        _, hist, _ = convert_messages(messages)
        assert hist == [{'role': 'model', 'parts': [{'text': 'just text'}]}]
