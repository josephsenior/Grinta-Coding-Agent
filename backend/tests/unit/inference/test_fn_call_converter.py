"""Tests for backend.inference.fn_call_converter — core conversion utilities."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest

from backend.core.errors import (
    FunctionCallConversionError,
    FunctionCallValidationError,
)
from backend.inference.fn_call_converter import (
    STOP_WORDS,
    ExampleStepBuilder,
    _convert_parameter_value,
    _convert_to_array,
    _convert_to_integer,
    _extract_parameter_schema,
    _find_tool_result_match,
    _fix_stopword,
    _format_parameter,
    _format_tool_call_string,
    _parse_tool_call_arguments,
    _validate_enum_constraint,
    _validate_parameter_allowed,
    _validate_required_parameters,
    _validate_tool_call_structure,
    convert_fncall_messages_to_non_fncall_messages,
    convert_from_multiple_tool_calls_to_single_tool_call_messages,
    convert_non_fncall_messages_to_fncall_messages,
    convert_tool_call_to_string,
    convert_tools_to_description,
    get_fn_call_parse_telemetry_counters,
    reset_fn_call_parse_telemetry_counters,
)
from backend.inference.tool_result_format import (
    decode_tool_result_payload,
)


@pytest.fixture(autouse=True)
def _reset_parse_telemetry_counters():
    reset_fn_call_parse_telemetry_counters()
    yield
    reset_fn_call_parse_telemetry_counters()


# ── _validate_tool_call_structure ──────────────────────────────────────


class TestValidateToolCallStructure:
    def test_valid(self):
        tc = {'function': {'name': 'f'}, 'id': '1', 'type': 'function'}
        _validate_tool_call_structure(tc)  # no error

    def test_missing_function(self):
        with pytest.raises(FunctionCallConversionError, match='function'):
            _validate_tool_call_structure({'id': '1', 'type': 'function'})

    def test_missing_id(self):
        with pytest.raises(FunctionCallConversionError, match='id'):
            _validate_tool_call_structure({'function': {}, 'type': 'function'})

    def test_missing_type(self):
        with pytest.raises(FunctionCallConversionError, match='type'):
            _validate_tool_call_structure({'function': {}, 'id': '1'})

    def test_wrong_type(self):
        with pytest.raises(FunctionCallConversionError, match='function'):
            _validate_tool_call_structure({'function': {}, 'id': '1', 'type': 'tool'})


# ── _parse_tool_call_arguments ─────────────────────────────────────────


class TestParseToolCallArguments:
    def test_valid_json(self):
        tc = {'function': {'arguments': '{"key": "val"}'}}
        assert _parse_tool_call_arguments(tc) == {'key': 'val'}

    def test_invalid_json(self):
        tc = {'function': {'arguments': 'not json'}}
        with pytest.raises(FunctionCallConversionError, match='JSON'):
            _parse_tool_call_arguments(tc)


# ── _format_parameter ─────────────────────────────────────────────────


class TestFormatParameter:
    def test_simple_string(self):
        result = _format_parameter('name', 'value')
        assert '<parameter=name>value</parameter>' in result

    def test_multiline_string(self):
        result = _format_parameter('code', 'line1\nline2')
        assert '<parameter=code>\nline1\nline2\n</parameter>' in result

    def test_list_value(self):
        result = _format_parameter('items', [1, 2, 3])
        assert json.dumps([1, 2, 3]) in result

    def test_dict_value(self):
        result = _format_parameter('data', {'a': 1})
        assert json.dumps({'a': 1}) in result

    def test_integer_value(self):
        result = _format_parameter('count', 42)
        assert '42' in result


# ── _format_tool_call_string ──────────────────────────────────────────


class TestFormatToolCallString:
    def test_basic(self):
        result = _format_tool_call_string('test_fn', {'x': '1', 'y': '2'})
        assert '<function=test_fn>' in result
        assert '</function>' in result
        assert '<parameter=x>1</parameter>' in result
        assert '<parameter=y>2</parameter>' in result

    def test_empty_args(self):
        result = _format_tool_call_string('empty', {})
        assert '<function=empty>' in result
        assert '</function>' in result


# ── convert_tool_call_to_string ────────────────────────────────────────


class TestConvertToolCallToString:
    def test_basic(self):
        tc = {
            'function': {'name': 'my_fn', 'arguments': '{"cmd": "ls"}'},
            'id': '1',
            'type': 'function',
        }
        result = convert_tool_call_to_string(tc)
        assert '<function=my_fn>' in result
        assert '<parameter=cmd>ls</parameter>' in result

    def test_invalid_structure(self):
        with pytest.raises(FunctionCallConversionError):
            convert_tool_call_to_string({'id': '1'})


# ── convert_tools_to_description ───────────────────────────────────────


class TestConvertToolsToDescription:
    def test_basic(self):
        tools = [
            {
                'type': 'function',
                'function': {
                    'name': 'my_tool',
                    'description': 'Does stuff',
                    'parameters': {
                        'properties': {'x': {'type': 'string', 'description': 'input'}},
                        'required': ['x'],
                    },
                },
            }
        ]
        result = convert_tools_to_description(tools)
        assert 'my_tool' in result
        assert 'Does stuff' in result
        assert '(1) x (string, required)' in result

    def test_no_params(self):
        tools = [{'type': 'function', 'function': {'name': 't', 'description': 'd'}}]
        result = convert_tools_to_description(tools)
        assert 'No parameters' in result

    def test_optional_param(self):
        tools = [
            {
                'type': 'function',
                'function': {
                    'name': 't',
                    'description': 'd',
                    'parameters': {
                        'properties': {'opt': {'type': 'integer', 'description': 'o'}},
                        'required': [],
                    },
                },
            }
        ]
        result = convert_tools_to_description(tools)
        assert 'optional' in result

    def test_enum_values(self):
        tools = [
            {
                'type': 'function',
                'function': {
                    'name': 't',
                    'description': 'd',
                    'parameters': {
                        'properties': {
                            'mode': {
                                'type': 'string',
                                'description': 'm',
                                'enum': ['a', 'b'],
                            }
                        },
                        'required': [],
                    },
                },
            }
        ]
        result = convert_tools_to_description(tools)
        assert '`a`' in result
        assert '`b`' in result

    def test_multiple_tools(self):
        tools = [
            {'type': 'function', 'function': {'name': 't1', 'description': 'd1'}},
            {'type': 'function', 'function': {'name': 't2', 'description': 'd2'}},
        ]
        result = convert_tools_to_description(tools)
        assert '#1' in result
        assert '#2' in result


# ── _fix_stopword ──────────────────────────────────────────────────────


class TestFixStopword:
    def test_missing_closing_is_unchanged(self):
        s = '<function=foo>\n<parameter=x>1</parameter>'
        assert _fix_stopword(s) == s

    def test_partial_closing_is_unchanged(self):
        s = '<function=foo>\n<parameter=x>1</parameter>\n</'
        assert _fix_stopword(s) == s

    def test_no_function_tag_unchanged(self):
        s = 'just plain text'
        assert _fix_stopword(s) == s

    def test_multiple_function_tags_unchanged(self):
        s = '<function=a>\n</function>\n<function=b>\n</function>'
        assert _fix_stopword(s) == s


# ── strict malformed parameter handling ────────────────────────────────


class TestMalformedParameterHandling:
    def test_malformed_parameter_tag_is_rejected(self):
        tools = [
            {
                'type': 'function',
                'function': {
                    'name': 'my_fn',
                    'description': 'test',
                    'parameters': {
                        'properties': {'cmd': {'type': 'string', 'description': 'c'}},
                        'required': ['cmd'],
                    },
                },
            }
        ]
        messages = [
            {
                'role': 'assistant',
                'content': ('<function=my_fn><parameter=cmd=ls</parameter></function>'),
            }
        ]

        with pytest.raises(
            FunctionCallValidationError,
            match='Malformed parameter block',
        ):
            convert_non_fncall_messages_to_fncall_messages(messages, tools)


# ── _convert_to_integer / _convert_to_array ────────────────────────────


class TestTypeConverters:
    def test_convert_to_integer_valid(self):
        assert _convert_to_integer('count', '42') == 42

    def test_convert_to_integer_invalid(self):
        with pytest.raises(FunctionCallValidationError, match='integer'):
            _convert_to_integer('count', 'abc')

    def test_convert_to_array_valid(self):
        assert _convert_to_array('items', '[1, 2, 3]') == [1, 2, 3]

    def test_convert_to_array_invalid(self):
        with pytest.raises(FunctionCallValidationError, match='array'):
            _convert_to_array('items', 'not json')


# ── _validate_parameter_allowed ────────────────────────────────────────


class TestValidateParameterAllowed:
    def test_allowed(self):
        _validate_parameter_allowed('x', {'x', 'y'}, 'fn')  # no error

    def test_not_allowed(self):
        with pytest.raises(FunctionCallValidationError, match='not allowed'):
            _validate_parameter_allowed('z', {'x', 'y'}, 'fn')

    def test_empty_allowed_always_ok(self):
        _validate_parameter_allowed('anything', set(), 'fn')  # no error


# ── _validate_required_parameters ──────────────────────────────────────


class TestValidateRequiredParameters:
    def test_all_present(self):
        _validate_required_parameters({'a', 'b'}, {'a', 'b'}, 'fn')  # no error

    def test_missing(self):
        with pytest.raises(FunctionCallValidationError, match='Missing'):
            _validate_required_parameters({'a'}, {'a', 'b'}, 'fn')


# ── _validate_enum_constraint ──────────────────────────────────────────


class TestValidateEnumConstraint:
    def test_valid_enum(self):
        tool = {'parameters': {'properties': {'mode': {'enum': ['a', 'b']}}}}
        _validate_enum_constraint('mode', 'a', tool, 'fn')  # no error

    def test_invalid_enum(self):
        tool = {'parameters': {'properties': {'mode': {'enum': ['a', 'b']}}}}
        with pytest.raises(FunctionCallValidationError, match='one of'):
            _validate_enum_constraint('mode', 'c', tool, 'fn')

    def test_no_enum(self):
        tool = {'parameters': {'properties': {'mode': {'type': 'string'}}}}
        _validate_enum_constraint('mode', 'anything', tool, 'fn')  # no error

    def test_no_parameters(self):
        _validate_enum_constraint('mode', 'x', {}, 'fn')  # no error


# ── _extract_parameter_schema ──────────────────────────────────────────


class TestExtractParameterSchema:
    def test_full_schema(self):
        tool = {
            'parameters': {
                'required': ['x'],
                'properties': {
                    'x': {'type': 'string'},
                    'y': {'type': 'integer'},
                },
            }
        }
        result = _extract_parameter_schema(tool)
        assert result['required_params'] == {'x'}
        assert result['allowed_params'] == {'x', 'y'}
        assert result['param_name_to_type']['x'] == 'string'

    def test_no_parameters(self):
        result = _extract_parameter_schema({})
        assert result['required_params'] == set()
        assert result['allowed_params'] == set()


# ── _convert_parameter_value ───────────────────────────────────────────


class TestConvertParameterValue:
    def test_string_passthrough(self):
        assert _convert_parameter_value('x', 'hello', {'x': 'string'}) == 'hello'

    def test_integer_conversion(self):
        assert _convert_parameter_value('x', '42', {'x': 'integer'}) == 42

    def test_array_conversion(self):
        assert _convert_parameter_value('x', '[1,2]', {'x': 'array'}) == [1, 2]

    def test_unknown_param(self):
        assert _convert_parameter_value('z', 'val', {'x': 'string'}) == 'val'


# ── ExampleStepBuilder ─────────────────────────────────────────────────


class TestExampleStepBuilder:
    def test_empty_tools(self):
        builder = ExampleStepBuilder(set())
        assert builder.build_all_steps() == ''

    def test_with_execute_bash(self):
        builder = ExampleStepBuilder({'execute_bash'})
        result = builder.build_all_steps()
        assert 'execute_bash' in result

    def test_with_finish(self):
        builder = ExampleStepBuilder({'finish'})
        result = builder.build_all_steps()
        assert 'finish' in result

    def test_text_editor(self):
        builder = ExampleStepBuilder({'text_editor'})
        result = builder.build_all_steps()
        assert 'text_editor' in result


# ── convert_fncall_messages_to_non_fncall_messages ─────────────────────


class TestConvertFncallToNonFncall:
    def _make_tool(self, name='my_fn'):
        return {
            'type': 'function',
            'function': {
                'name': name,
                'description': 'test',
                'parameters': {
                    'properties': {'cmd': {'type': 'string', 'description': 'c'}},
                    'required': ['cmd'],
                },
            },
        }

    def test_system_message_gets_suffix(self):
        tools = [self._make_tool()]
        messages = [{'role': 'system', 'content': 'You are helpful'}]
        result = convert_fncall_messages_to_non_fncall_messages(messages, tools)
        assert 'You have access to the following functions' in result[0]['content']

    def test_user_message_preserved(self):
        tools = [self._make_tool()]
        messages = [
            {'role': 'system', 'content': 'sys'},
            {'role': 'user', 'content': 'Hello'},
        ]
        result = convert_fncall_messages_to_non_fncall_messages(
            messages, tools, add_in_context_learning_example=False
        )
        assert result[1]['role'] == 'user'

    def test_tool_message_converted_to_user(self):
        tools = [self._make_tool()]
        messages = [
            {'role': 'tool', 'name': 'my_fn', 'content': 'result here'},
        ]
        result = convert_fncall_messages_to_non_fncall_messages(
            messages, tools, add_in_context_learning_example=False
        )
        assert result[0]['role'] == 'user'
        payload = decode_tool_result_payload(result[0]['content'][0]['text'])
        assert payload is not None
        assert payload[0] == 'my_fn'
        assert payload[1] == 'result here'

    def test_assistant_malformed_function_tag_not_marked_as_tool_call(self):
        tools = [self._make_tool()]
        messages = [
            {
                'role': 'assistant',
                'content': '<function=my_fn><parameter=cmd>ls</parameter>',
            }
        ]
        result = convert_fncall_messages_to_non_fncall_messages(messages, tools)
        assert result[0]['role'] == 'assistant'
        assert 'tool_calls' not in result[0]

    def test_duplicate_parameter_is_rejected(self):
        tools = [self._make_tool()]
        messages = [
            {
                'role': 'assistant',
                'content': (
                    '<function=my_fn>'
                    '<parameter=cmd>ls</parameter>'
                    '<parameter=cmd>pwd</parameter>'
                    '</function>'
                ),
            }
        ]
        with pytest.raises(FunctionCallValidationError, match='Duplicate parameter'):
            convert_non_fncall_messages_to_fncall_messages(messages, tools)

    def test_trailing_text_after_last_parameter_is_rejected(self):
        tools = [self._make_tool()]
        messages = [
            {
                'role': 'assistant',
                'content': (
                    '<function=my_fn>'
                    '<parameter=cmd>ls</parameter>'
                    ' trailing-junk '
                    '</function>'
                ),
            }
        ]
        with pytest.raises(
            FunctionCallValidationError, match='Unexpected trailing text'
        ):
            convert_non_fncall_messages_to_fncall_messages(messages, tools)


class TestParseTelemetryCounters:
    def _make_tool(self, name='my_fn'):
        return {
            'type': 'function',
            'function': {
                'name': name,
                'description': 'test',
                'parameters': {
                    'properties': {'cmd': {'type': 'string', 'description': 'c'}},
                    'required': ['cmd'],
                },
            },
        }

    def test_strict_parse_success_counter_increments(self):
        tools = [self._make_tool()]
        messages = [
            {
                'role': 'assistant',
                'content': '<function=my_fn><parameter=cmd>ls</parameter></function>',
            }
        ]

        convert_non_fncall_messages_to_fncall_messages(messages, tools)

        counters = get_fn_call_parse_telemetry_counters()
        assert counters['strict_parse_success'] == 1
        assert counters['strict_parse_failure'] == 0
        assert counters['malformed_payload_rejection'] == 0

    def test_strict_parse_failure_counter_increments_for_unclosed_function_tag(self):
        tools = [self._make_tool()]
        messages = [
            {
                'role': 'assistant',
                'content': '<function=my_fn><parameter=cmd>ls</parameter>',
            }
        ]

        convert_non_fncall_messages_to_fncall_messages(messages, tools)

        counters = get_fn_call_parse_telemetry_counters()
        assert counters['strict_parse_success'] == 0
        assert counters['strict_parse_failure'] == 1
        assert counters['malformed_payload_rejection'] == 0

    def test_malformed_payload_rejection_counter_increments(self):
        tools = [self._make_tool()]
        messages = [
            {
                'role': 'user',
                'content': (
                    '<app_tool_result_json>{"tool_name":"my_fn",'
                    '"content":</app_tool_result_json>'
                ),
            }
        ]

        convert_non_fncall_messages_to_fncall_messages(messages, tools)

        counters = get_fn_call_parse_telemetry_counters()
        assert counters['strict_parse_success'] == 0
        assert counters['strict_parse_failure'] == 0
        assert counters['malformed_payload_rejection'] == 1


# ── convert_from_multiple_tool_calls_to_single_tool_call_messages ──────


class TestConvertMultipleToSingle:
    def test_single_tool_call_passthrough(self):
        messages = [
            {
                'role': 'assistant',
                'content': 'thinking',
                'tool_calls': [
                    {
                        'id': 't1',
                        'type': 'function',
                        'function': {'name': 'f', 'arguments': '{}'},
                    }
                ],
            },
            {'role': 'tool', 'tool_call_id': 't1', 'content': 'done'},
        ]
        result = convert_from_multiple_tool_calls_to_single_tool_call_messages(
            cast(list[dict[Any, Any]], messages)
        )
        assert len(result) == 2

    def test_multiple_tool_calls_split(self):
        messages = [
            {
                'role': 'assistant',
                'content': 'doing both',
                'tool_calls': [
                    {
                        'id': 't1',
                        'type': 'function',
                        'function': {'name': 'f1', 'arguments': '{}'},
                    },
                    {
                        'id': 't2',
                        'type': 'function',
                        'function': {'name': 'f2', 'arguments': '{}'},
                    },
                ],
            },
            {'role': 'tool', 'tool_call_id': 't1', 'content': 'r1'},
            {'role': 'tool', 'tool_call_id': 't2', 'content': 'r2'},
        ]
        result = convert_from_multiple_tool_calls_to_single_tool_call_messages(
            cast(list[dict[Any, Any]], messages)
        )
        # Should have: assistant(t1), tool(t1), assistant(t2), tool(t2)
        assert len(result) == 4

    def test_pending_raises_if_not_ignored(self):
        messages = [
            {
                'role': 'assistant',
                'content': '',
                'tool_calls': [
                    {
                        'id': 't1',
                        'type': 'function',
                        'function': {'name': 'f1', 'arguments': '{}'},
                    },
                    {
                        'id': 't2',
                        'type': 'function',
                        'function': {'name': 'f2', 'arguments': '{}'},
                    },
                ],
            },
        ]
        with pytest.raises(FunctionCallConversionError, match='pending'):
            convert_from_multiple_tool_calls_to_single_tool_call_messages(messages)

    def test_pending_ignored_when_flag_set(self):
        messages = [
            {
                'role': 'assistant',
                'content': '',
                'tool_calls': [
                    {
                        'id': 't1',
                        'type': 'function',
                        'function': {'name': 'f1', 'arguments': '{}'},
                    },
                    {
                        'id': 't2',
                        'type': 'function',
                        'function': {'name': 'f2', 'arguments': '{}'},
                    },
                ],
            },
        ]
        result = convert_from_multiple_tool_calls_to_single_tool_call_messages(
            messages, ignore_final_tool_result=True
        )
        assert isinstance(result, list)


# ── Structured tool result decode ─────────────────────────────────────


class TestRegexPatterns:
    def test_tool_result_decode(self):
        text = '<app_tool_result_json>{"tool_name":"my_tool","content":"some output"}</app_tool_result_json>'
        decoded = decode_tool_result_payload(text)
        assert decoded is not None
        assert decoded[0] == 'my_tool'

    def test_tool_result_decode_tolerates_spacing_variants(self):
        text = '<app_tool_result_json> {"tool_name":"my_tool","content":"some output"} </app_tool_result_json>'
        decoded = decode_tool_result_payload(text)
        assert decoded is not None
        assert decoded[0] == 'my_tool'

    def test_convert_non_fncall_message_parses_spaced_function_tag(self):
        tools = [
            {
                'type': 'function',
                'function': {
                    'name': 'my_fn',
                    'description': 'Test function',
                    'parameters': {
                        'type': 'object',
                        'properties': {'x': {'type': 'string'}},
                        'required': ['x'],
                    },
                },
            }
        ]
        messages = [
            {
                'role': 'assistant',
                'content': 'prep text <function = my_fn ><parameter = x >value</parameter></function>',
            }
        ]

        result = convert_non_fncall_messages_to_fncall_messages(messages, tools)

        assert len(result) == 1
        assert result[0]['role'] == 'assistant'
        assert result[0]['tool_calls'][0]['function']['name'] == 'my_fn'
        assert json.loads(result[0]['tool_calls'][0]['function']['arguments']) == {
            'x': 'value'
        }
        assert result[0]['content'] == 'prep text'

    def test_stop_words(self):
        assert '</function' in STOP_WORDS

    def test_tool_result_decode_payload_with_colons_and_urls(self):
        text = (
            '<app_tool_result_json>'
            '{"tool_name":"browser","content":"see https://example.com:8443/path: done"}'
            '</app_tool_result_json>'
        )
        decoded = decode_tool_result_payload(text)
        assert decoded is not None
        assert decoded[0] == 'browser'
        assert 'https://example.com:8443/path' in str(decoded[1])

    def test_find_tool_result_match_on_multiline_list_content(self):
        content = [
            {
                'type': 'text',
                'text': '<app_tool_result_json>{"tool_name":"t","content":"out:line"}</app_tool_result_json>',
            },
        ]
        assert _find_tool_result_match(content) is not None
