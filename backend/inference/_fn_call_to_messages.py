"""Chunk _fn_call_to_messages of fn_call_converter.

Extracted from backend/inference/fn_call_converter.py to keep the
parent module under the per-file LOC budget.
"""

from __future__ import annotations

import copy
import json
import logging
import re
from collections.abc import Iterable
from typing import Any, NoReturn

from backend.core.errors import (
    FunctionCallConversionError,
    FunctionCallValidationError,
)
from backend.inference._fn_call_convert import (  # noqa: F401
    _process_system_message,
    _process_user_message,
    convert_tools_to_description,
)
from backend.inference._fn_call_examples import (  # noqa: F401
    _MALFORMED_PAYLOAD_REJECTION,
    _STRICT_PARSE_FAILURE,
    _STRICT_PARSE_SUCCESS,
    _XML_TRAILING_TEXT,
    IN_CONTEXT_LEARNING_EXAMPLE_PREFIX,
    IN_CONTEXT_LEARNING_EXAMPLE_SUFFIX,
    SYSTEM_PROMPT_SUFFIX_TEMPLATE,
    _increment_parse_counter,
    _log_xml_parser_diagnostics,
)
from backend.inference.tool_result_format import (
    TOOL_RESULT_BLOCK_PREFIX,
    TOOL_RESULT_BLOCK_SUFFIX,
    decode_tool_result_payload,
    encode_tool_result_payload,
)

logger = logging.getLogger(__name__)

def convert_fncall_messages_to_non_fncall_messages(
    messages: list[dict],
    tools: list[dict],
    add_in_context_learning_example: bool = True,
    mode: str = 'agent',
) -> list[dict]:
    """Convert function calling messages to non-function calling messages."""
    messages = copy.deepcopy(messages)
    formatted_tools = convert_tools_to_description(tools)
    system_prompt_suffix = SYSTEM_PROMPT_SUFFIX_TEMPLATE.format(
        description=formatted_tools
    )
    converted_messages: list[dict[str, Any]] = []
    first_user_message_encountered = False
    for message in messages:
        message_payloads, first_user_message_encountered = _convert_single_message(
            message,
            tools,
            system_prompt_suffix,
            add_in_context_learning_example,
            first_user_message_encountered,
            mode=mode,
        )
        converted_messages.extend(message_payloads)
    return converted_messages


def _convert_single_message(
    message: dict,
    tools: list[dict],
    system_prompt_suffix: str,
    add_in_context_learning_example: bool,
    first_user_message_encountered: bool,
    mode: str = 'agent',
) -> tuple[list[dict], bool]:
    role = message['role']
    content = message['content']
    if role == 'assistant':
        return [_convert_assistant_message(content)], first_user_message_encountered
    if role == 'system':
        return (
            [_process_system_message(content, system_prompt_suffix)],
            first_user_message_encountered,
        )
    if role == 'user':
        user_msg, first_user_message_encountered = _process_user_message(
            content,
            tools,
            add_in_context_learning_example,
            first_user_message_encountered,
            mode=mode,
        )
        return [user_msg], first_user_message_encountered
    if role == 'tool':
        return ([_convert_tool_message(message)], first_user_message_encountered)
    return ([{'role': role, 'content': content}], first_user_message_encountered)


def _convert_assistant_message(content: Any) -> dict:
    if isinstance(content, str) and _parse_function_call_from_text(content):
        return {'role': 'assistant', 'content': content, 'tool_calls': []}
    return {'role': 'assistant', 'content': content}


def _convert_tool_message(message: dict) -> dict:
    tool_name = message.get('name', 'unknown_tool')
    content_list = _format_tool_content(message.get('content'), tool_name)
    if 'cache_control' in message and content_list:
        content_list[-1]['cache_control'] = message['cache_control']
    return {'role': 'user', 'content': content_list}


def _format_tool_content(content: Any, tool_name: str) -> list[dict]:
    return [{'type': 'text', 'text': encode_tool_result_payload(tool_name, content)}]


def _extract_and_validate_params(
    matching_tool: dict, param_matches: Iterable[Any], fn_name: str
) -> dict:
    """Extract and validate parameters from function call matches."""
    # Extract parameter schema information
    param_schema = _extract_parameter_schema(matching_tool)

    # Process each parameter match
    params = {}
    found_params = set()

    for param_match in param_matches:
        param_name = param_match.group(1)
        param_value = param_match.group(2)

        if param_name in found_params:
            msg = (
                f"Duplicate parameter '{param_name}' provided for function '{fn_name}'. "
                'Each parameter may appear at most once.'
            )
            raise FunctionCallValidationError(msg)

        # Validate parameter is allowed
        _validate_parameter_allowed(param_name, param_schema['allowed_params'], fn_name)

        # Convert parameter value based on type
        converted_value = _convert_parameter_value(
            param_name, param_value, param_schema['param_name_to_type']
        )

        # Validate enum constraints
        _validate_enum_constraint(param_name, converted_value, matching_tool, fn_name)

        params[param_name] = converted_value
        found_params.add(param_name)

    # Validate all required parameters are present
    _validate_required_parameters(
        found_params, param_schema['required_params'], fn_name
    )

    return params


def _extract_parameter_schema(matching_tool: dict) -> dict:
    """Extract parameter schema information from matching tool."""
    required_params = set()
    allowed_params = set()
    param_name_to_type = {}

    if 'parameters' in matching_tool:
        params_def = matching_tool['parameters']

        # Extract required parameters
        if 'required' in params_def:
            required_params = set(params_def.get('required', []))

        # Extract allowed parameters and types
        if 'properties' in params_def:
            allowed_params = set(params_def['properties'].keys())
            param_name_to_type = {
                name: val.get('type', 'string')
                for name, val in params_def['properties'].items()
            }

    return {
        'required_params': required_params,
        'allowed_params': allowed_params,
        'param_name_to_type': param_name_to_type,
    }


def _validate_parameter_allowed(
    param_name: str, allowed_params: set, fn_name: str
) -> None:
    """Validate that parameter is allowed for the function."""
    if allowed_params and param_name not in allowed_params:
        msg = f"Parameter '{param_name}' is not allowed for function '{fn_name}'. Allowed parameters: {allowed_params}"
        raise FunctionCallValidationError(
            msg,
        )


def _convert_parameter_value(
    param_name: str, param_value: str, param_name_to_type: dict
) -> Any:
    """Convert parameter value based on its expected type."""
    if param_name not in param_name_to_type:
        return param_value

    param_type = param_name_to_type[param_name]

    if param_type == 'integer':
        return _convert_to_integer(param_name, param_value)
    if param_type == 'array':
        return _convert_to_array(param_name, param_value)
    return param_value


def _convert_to_integer(param_name: str, param_value: str) -> int:
    """Convert parameter value to integer."""
    try:
        return int(param_value)
    except ValueError as e:
        msg = f"Parameter '{param_name}' is expected to be an integer."
        raise FunctionCallValidationError(msg) from e


def _convert_to_array(param_name: str, param_value: str) -> list[Any]:
    """Convert parameter value to array."""
    try:
        return json.loads(param_value)
    except json.JSONDecodeError as e:
        msg = f"Parameter '{param_name}' is expected to be an array."
        raise FunctionCallValidationError(msg) from e


def _validate_enum_constraint(
    param_name: str, param_value: Any, matching_tool: dict, fn_name: str
) -> None:
    """Validate enum constraints for parameter."""
    if 'parameters' not in matching_tool:
        return

    properties = matching_tool['parameters'].get('properties', {})
    if param_name not in properties:
        return

    param_def = properties[param_name]
    if 'enum' not in param_def:
        return

    if param_value not in param_def['enum']:
        msg = f"Parameter '{param_name}' is expected to be one of {param_def['enum']}."
        raise FunctionCallValidationError(msg)


def _validate_required_parameters(
    found_params: set, required_params: set, fn_name: str
) -> None:
    """Validate that all required parameters are present."""
    if missing_params := required_params - found_params:
        msg = f"Missing required parameters for function '{fn_name}': {missing_params}"
        raise FunctionCallValidationError(msg)


def _fix_stopword(content: str) -> str:
    """Return content unchanged.

    Strict mode: malformed/truncated function-call payloads are no longer
    auto-repaired and must fail parsing as-is.
    """
    return content


def _process_system_message_reverse(content: Any, system_prompt_suffix: str) -> dict:
    """Process system message by removing the tool suffix (for reverse conversion)."""
    content = _trim_system_prompt_suffix(content, system_prompt_suffix)
    return {'role': 'system', 'content': content}


def _process_user_message_reverse(
    content: Any, tools: list[dict], mode: str = 'agent'
) -> dict:
    """Process user message for reverse conversion, removing examples and converting tool results.

    If the user message contains a tool result (detected by EXECUTION RESULT pattern),
    it should be converted back to a 'tool' role message for proper round-trip conversion.
    """
    content = _remove_in_context_learning_examples(content, tools, mode=mode)

    # Structured tool result blocks are the only accepted non-native format.
    if parsed := _extract_structured_tool_result(content):
        tool_name, tool_content = parsed
        return {'role': 'tool', 'name': tool_name, 'content': tool_content}

    return {'role': 'user', 'content': content}


def _remove_in_context_learning_examples(
    content: Any,
    tools: list[dict],
    mode: str = 'agent',
) -> Any:
    """Remove in-context learning examples from content."""
    if isinstance(content, str):
        return _remove_examples_from_string(content, tools, mode=mode)
    if isinstance(content, list):
        return _remove_examples_from_list(content, tools, mode=mode)
    _raise_unexpected_content_type(content)


def _remove_examples_from_string(
    content: str,
    tools: list[dict],
    mode: str = 'agent',
) -> str:
    """Remove examples from string content."""
    example_prefix = IN_CONTEXT_LEARNING_EXAMPLE_PREFIX(tools, mode)
    if content.startswith(example_prefix):
        content = content.replace(example_prefix, '', 1)
    if content.endswith(IN_CONTEXT_LEARNING_EXAMPLE_SUFFIX):
        content = content.replace(IN_CONTEXT_LEARNING_EXAMPLE_SUFFIX, '', 1)
    return content


def _remove_examples_from_list(
    content: list,
    tools: list[dict],
    mode: str = 'agent',
) -> list:
    """Remove examples from list content."""
    example_prefix = IN_CONTEXT_LEARNING_EXAMPLE_PREFIX(tools, mode)
    for item in content:
        if item['type'] == 'text':
            if item['text'].startswith(example_prefix):
                item['text'] = item['text'].replace(example_prefix, '', 1)
            if item['text'].endswith(IN_CONTEXT_LEARNING_EXAMPLE_SUFFIX):
                item['text'] = item['text'].replace(
                    IN_CONTEXT_LEARNING_EXAMPLE_SUFFIX, '', 1
                )
    return content


def _find_tool_result_match(content: Any) -> Any:
    """Return decoded structured tool-result payload or None."""
    return _extract_structured_tool_result(content)


def _extract_structured_tool_result(content: Any) -> tuple[str, Any] | None:
    """Decode strict structured tool result payload from string or text list."""
    if isinstance(content, str):
        decoded = decode_tool_result_payload(content)
        if decoded is None and _looks_like_tool_result_candidate(content):
            _increment_parse_counter(_MALFORMED_PAYLOAD_REJECTION)
        return decoded
    if isinstance(content, list):
        for item in content:
            if item.get('type') != 'text':
                continue
            text = item.get('text', '')
            decoded = decode_tool_result_payload(text)
            if decoded is None and _looks_like_tool_result_candidate(text):
                _increment_parse_counter(_MALFORMED_PAYLOAD_REJECTION)
            if decoded is not None:
                return decoded
        return None
    _raise_unexpected_content_type(content)


def _looks_like_tool_result_candidate(text: str) -> bool:
    """Return whether text appears to be intended as a structured tool-result block."""
    stripped = (text or '').strip()
    return TOOL_RESULT_BLOCK_PREFIX in stripped or TOOL_RESULT_BLOCK_SUFFIX in stripped


def _trim_system_prompt_suffix(content: Any, system_prompt_suffix: str) -> Any:
    """Trim system prompt suffix from content."""
    if isinstance(content, str):
        return content.split(system_prompt_suffix)[0]
    if isinstance(content, list) and content and content[-1]['type'] == 'text':
        content[-1]['text'] = content[-1]['text'].split(system_prompt_suffix)[0]
    return content


_FN_OPEN_RE = re.compile(
    '<\\s*function(?:(?:\\s*=\\s*|\\s+name\\s*=\\s*[\x27\x22]?)([a-zA-Z0-9_\\-]+)[\x27\x22]?)?\\s*>',
    re.IGNORECASE,
)
_FN_CLOSE_RE = re.compile(r'</\s*function\s*>', re.IGNORECASE)
_PARAM_OPEN_HAS_RE = re.compile(r'<\s*parameter[\s=>]', re.IGNORECASE)
_PARAM_BLOCK_RE = re.compile(
    '<\\s*parameter(?:(?:\\s*=\\s*|\\s+name\\s*=\\s*[\x27\x22]?)([a-zA-Z0-9_\\-]+)[\x27\x22]?)?\\s*>(.*?)</\\s*parameter\\s*>',
    re.DOTALL | re.IGNORECASE,
)


def _parse_function_call_from_text(text: str) -> dict[str, Any] | None:
    """Parse the first strict function-call block from plain text."""
    open_m = _FN_OPEN_RE.search(text)
    if open_m is None:
        return None
    fn_name = (open_m.group(1) or '').strip()
    open_end = open_m.end(0)

    close_m = _FN_CLOSE_RE.search(text, open_end)
    if close_m is None:
        _increment_parse_counter(_STRICT_PARSE_FAILURE)
        return None

    fn_body = text[open_end : close_m.start(0)]
    return {
        'fn_name': fn_name,
        'fn_body': fn_body,
        'start': open_m.start(0),
        'end': close_m.end(0),
    }


def _find_tool_call_match(content: Any) -> Any:
    """Find parsed tool call payload in content.

    Returns a dict with parsed fields and source location, or ``None``.
    """
    if isinstance(content, str):
        parsed = _parse_function_call_from_text(content)
        if parsed is None:
            return None
        parsed['container'] = 'str'
        return parsed
    if isinstance(content, list):
        for idx, item in enumerate(content):
            if item.get('type') != 'text':
                continue
            parsed = _parse_function_call_from_text(item.get('text', ''))
            if parsed is None:
                continue
            parsed['container'] = 'list'
            parsed['item_index'] = idx
            return parsed
        return None
    return None


def _extract_tool_call_info(tool_call_match: Any) -> tuple[str, str]:
    """Extract function name and body from parsed tool call payload."""
    return str(tool_call_match['fn_name']), str(tool_call_match['fn_body'])


def _find_matching_tool(fn_name: str, tools: list[dict]) -> dict:
    """Find matching tool for function name."""
    matching_tool = next(
        (
            tool['function']
            for tool in tools
            if tool['type'] == 'function' and tool['function']['name'] == fn_name
        ),
        None,
    )
    if not matching_tool:
        available_tools = [
            tool['function']['name'] for tool in tools if tool['type'] == 'function'
        ]
        msg = f"Function '{fn_name}' not found in available tools: {available_tools}"
        raise FunctionCallValidationError(msg)
    return matching_tool


def _create_tool_call(
    fn_name: str, fn_body: str, matching_tool: dict, tool_call_counter: int
) -> tuple[dict, int]:
    """Create tool call object and increment counter."""
    params = _extract_and_validate_params(
        matching_tool,
        _iter_parameter_matches(fn_body),
        fn_name,
    )
    tool_call_id = f'toolu_{tool_call_counter:02d}'
    tool_call = {
        'index': 1,
        'id': tool_call_id,
        'type': 'function',
        'function': {'name': fn_name, 'arguments': json.dumps(params)},
    }
    return tool_call, tool_call_counter + 1


def _iter_parameter_matches(
    fn_body: str,
    param_body: str | None = None,
) -> Iterable[Any]:
    """Yield regex-like parameter matches parsed via strict tag scanning.

    Args:
        fn_body: The full function body text that was iterated for matches.
        param_body: Optional alternate body to use for trailing text checks.
                    If None, fn_body is used.
    """
    iterated_body = param_body if param_body is not None else fn_body

    class _PseudoMatch:
        def __init__(self, name: str, value: str) -> None:
            self._name = name
            self._value = value

        def group(self, index: int) -> str:
            if index == 1:
                return self._name
            if index == 2:
                return self._value
            raise IndexError(index)

    last_end = 0
    param_count = 0
    for m in _PARAM_BLOCK_RE.finditer(iterated_body):
        param_name = (m.group(1) or '').strip()
        param_value = m.group(2)
        yield _PseudoMatch(param_name, param_value)
        last_end = m.end(0)
        param_count += 1

    # Detect unclosed <parameter> tags (open tag present but no closed match)
    open_count = len(_PARAM_OPEN_HAS_RE.findall(iterated_body))
    closed_count = len(_PARAM_BLOCK_RE.findall(iterated_body))
    if open_count > closed_count:
        _increment_parse_counter(_STRICT_PARSE_FAILURE)
        raise FunctionCallValidationError(
            'Malformed parameter block: missing closing </parameter> tag'
        )

    trailing = iterated_body[last_end:] if last_end else iterated_body
    if trailing.strip():
        _increment_parse_counter(_XML_TRAILING_TEXT)
        _log_xml_parser_diagnostics(
            fn_name='',
            fn_body=iterated_body,
            param_body=param_body,
            error_code=_XML_TRAILING_TEXT,
            trailing_text=trailing,
            last_end=last_end,
            param_count=param_count,
        )
        raise FunctionCallValidationError(
            f'Unexpected trailing text after last parameter inside function block: '
            f'"{trailing[:200]}"'
        )


def _trim_content_before_function(content: Any, tool_call_match: Any) -> Any:
    """Trim content before function call."""
    if isinstance(content, list):
        item_index = tool_call_match.get('item_index')
        if item_index is None:
            return content
        text = content[item_index].get('text', '')
        content[item_index]['text'] = text[: int(tool_call_match['start'])].strip()
    elif isinstance(content, str):
        content = content[: int(tool_call_match['start'])].strip()
    else:
        _raise_unexpected_content_type(content)
    return content


def _raise_unexpected_content_type(content: Any) -> NoReturn:
    """Raise a consistent conversion error for unsupported message content types."""
    msg = f'Unexpected content type {type(content)}. Expected str or list. Content: {content}'
    raise FunctionCallConversionError(msg)


def _process_assistant_message_for_conversion(
    content: Any,
    tools: list[dict],
    tool_call_counter: int,
    converted_messages: list[dict[str, Any]],
    system_prompt_suffix: str,
) -> int:
    """Process assistant message for converting to function calling format."""
    # Trim system prompt suffix
    content = _trim_system_prompt_suffix(content, system_prompt_suffix)

    if tool_call_match := _find_tool_call_match(content):
        try:
            # Extract tool call information
            fn_name, fn_body = _extract_tool_call_info(tool_call_match)

            # Find matching tool and validate
            matching_tool = _find_matching_tool(fn_name, tools)

            # Create tool call
            tool_call, tool_call_counter = _create_tool_call(
                fn_name, fn_body, matching_tool, tool_call_counter
            )

            # Trim content before function call
            content = _trim_content_before_function(content, tool_call_match)

            # Add to converted messages
            converted_messages.append(
                {'role': 'assistant', 'content': content, 'tool_calls': [tool_call]}
            )
            _increment_parse_counter(_STRICT_PARSE_SUCCESS)
        except (FunctionCallValidationError, FunctionCallConversionError):
            _increment_parse_counter(_STRICT_PARSE_FAILURE)
            raise
    else:
        # No tool call found, add as regular message
        converted_messages.append({'role': 'assistant', 'content': content})

    return tool_call_counter


def convert_non_fncall_messages_to_fncall_messages(
    messages: list[dict],
    tools: list[dict],
    mode: str = 'agent',
) -> list[dict]:
    """Convert non-function calling messages back to function calling messages."""
    messages = copy.deepcopy(messages)
    formatted_tools = convert_tools_to_description(tools)
    system_prompt_suffix = SYSTEM_PROMPT_SUFFIX_TEMPLATE.format(
        description=formatted_tools
    )
    converted_messages: list[dict[str, Any]] = []
    tool_call_counter = 1
    for message in messages:
        role = message['role']
        content = message['content'] or ''
        if role == 'assistant':
            tool_call_counter = _process_assistant_message_for_conversion(
                content,
                tools,
                tool_call_counter,
                converted_messages,
                system_prompt_suffix,
            )
        elif role == 'system':
            processed = _process_system_message_reverse(content, system_prompt_suffix)
            converted_messages.append(processed)
        elif role == 'user':
            processed = _process_user_message_reverse(content, tools, mode=mode)
            converted_messages.append(processed)
        else:
            converted_messages.append({'role': role, 'content': content})
    return converted_messages


def convert_from_multiple_tool_calls_to_single_tool_call_messages(
    messages: list[dict],
    ignore_final_tool_result: bool = False,
) -> list[dict]:
    """Break one message with multiple tool calls into multiple messages.

    Args:
        messages: List of message dictionaries
        ignore_final_tool_result: Whether to ignore pending tool calls at the end

    Returns:
        List of converted messages

    Raises:
        FunctionCallConversionError: If pending tool calls remain

    """
    converted_messages: list[dict[str, Any]] = []
    pending_tool_calls: dict[str, dict[str, Any]] = {}

    for message in messages:
        role = message['role']

        if role == 'assistant':
            _process_assistant_message(message, pending_tool_calls, converted_messages)
        elif role == 'tool':
            _process_tool_message(message, pending_tool_calls, converted_messages)
        else:
            _process_other_message(
                message, pending_tool_calls, converted_messages, role
            )

    if not ignore_final_tool_result and pending_tool_calls:
        msg = f'Found pending tool calls but no tool result: pending_tool_calls={pending_tool_calls!r}'
        raise FunctionCallConversionError(
            msg,
        )

    return converted_messages


def _process_assistant_message(
    message: dict,
    pending_tool_calls: dict[str, dict],
    converted_messages: list[dict[str, Any]],
) -> None:
    """Process assistant message with potential tool calls.

    Args:
        message: Assistant message
        pending_tool_calls: Dictionary of pending tool calls
        converted_messages: List to append converted messages to

    """
    if message.get('tool_calls') and len(message['tool_calls']) > 1:
        content = message['content']
        for i, tool_call in enumerate(message['tool_calls']):
            pending_tool_calls[tool_call['id']] = {
                'role': 'assistant',
                'content': content if i == 0 else '',
                'tool_calls': [tool_call],
            }
    else:
        converted_messages.append(message)


def _process_tool_message(
    message: dict,
    pending_tool_calls: dict[str, dict],
    converted_messages: list[dict[str, Any]],
) -> None:
    """Process tool result message.

    Args:
        message: Tool message
        pending_tool_calls: Dictionary of pending tool calls
        converted_messages: List to append converted messages to

    """
    if message['tool_call_id'] in pending_tool_calls:
        _tool_call_message = pending_tool_calls.pop(message['tool_call_id'])
        converted_messages.append(_tool_call_message)
    else:
        assert not pending_tool_calls, (
            f'Found pending tool calls but not found in pending list: {pending_tool_calls:=}'
        )

    converted_messages.append(message)


def _process_other_message(
    message: dict,
    pending_tool_calls: dict[str, dict],
    converted_messages: list[dict[str, Any]],
    role: str,
) -> None:
    """Process message with other roles.

    Args:
        message: Message with other role
        pending_tool_calls: Dictionary of pending tool calls
        converted_messages: List to append converted messages to
        role: Message role

    """
    assert not pending_tool_calls, (
        f'Found pending tool calls but not expect to handle it with role {role}: {pending_tool_calls:=}, {message:=}'
    )
    converted_messages.append(message)
