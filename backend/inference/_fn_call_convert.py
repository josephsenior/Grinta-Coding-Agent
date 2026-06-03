"""Chunk _fn_call_convert of fn_call_converter.

Extracted from backend/inference/fn_call_converter.py to keep the
parent module under the per-file LOC budget.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import threading
from collections.abc import Iterable
from threading import Lock
from typing import Any, NoReturn, cast

logger = logging.getLogger(__name__)

from backend.core.errors import FunctionCallConversionError
from backend.core.tool_arguments_json import parse_tool_arguments_object

def convert_tool_call_to_string(tool_call: dict) -> str:
    """Convert tool call to content in string format.

    Args:
        tool_call: Tool call dictionary

    Returns:
        String representation of tool call

    Raises:
        FunctionCallConversionError: If tool call format is invalid

    """
    _validate_tool_call_structure(tool_call)

    function_name = tool_call['function']['name']
    args = _parse_tool_call_arguments(tool_call)

    return _format_tool_call_string(function_name, args)


def _validate_tool_call_structure(tool_call: dict) -> None:
    """Validate tool call has required structure.

    Args:
        tool_call: Tool call dict to validate

    Raises:
        FunctionCallConversionError: If structure is invalid

    """
    if 'function' not in tool_call:
        msg = "Tool call must contain 'function' key."
        raise FunctionCallConversionError(msg)
    if 'id' not in tool_call:
        msg = "Tool call must contain 'id' key."
        raise FunctionCallConversionError(msg)
    if 'type' not in tool_call:
        msg = "Tool call must contain 'type' key."
        raise FunctionCallConversionError(msg)
    if tool_call['type'] != 'function':
        msg = "Tool call type must be 'function'."
        raise FunctionCallConversionError(msg)


def _parse_tool_call_arguments(tool_call: dict) -> dict:
    """Parse JSON arguments from tool call.

    Args:
        tool_call: Tool call containing arguments

    Returns:
        Parsed arguments dict

    Raises:
        FunctionCallConversionError: If arguments are invalid JSON

    """
    try:
        raw = tool_call['function']['arguments']
        if isinstance(raw, dict):
            return raw
        if not isinstance(raw, str):
            msg = f'tool call arguments must be str or dict, got {type(raw).__name__}'
            raise TypeError(msg)
        return parse_tool_arguments_object(raw)
    except (KeyError, TypeError, ValueError) as e:
        raw = tool_call.get('function', {}).get('arguments', '')
        preview = (
            raw if isinstance(raw, str) and len(raw) <= 240 else f'{str(raw)[:237]}...'
        )
        msg = f'Failed to parse arguments as JSON: {e}. Arguments: {preview}'
        raise FunctionCallConversionError(
            msg,
        ) from e


def _format_tool_call_string(function_name: str, args: dict) -> str:
    """Format tool call as XML-style string.

    Args:
        function_name: Name of the function
        args: Function arguments dict

    Returns:
        Formatted tool call string

    """
    ret = f'<function={function_name}>\n'

    for param_name, param_value in args.items():
        ret += _format_parameter(param_name, param_value)

    ret += '</function>'
    return ret


def _format_parameter(param_name: str, param_value: Any) -> str:
    """Format a single parameter for tool call string.

    Args:
        param_name: Parameter name
        param_value: Parameter value

    Returns:
        Formatted parameter string

    """
    is_multiline = isinstance(param_value, str) and '\n' in param_value

    ret = f'<parameter={param_name}>'
    if is_multiline:
        ret += '\n'

    if isinstance(param_value, list | dict):
        ret += json.dumps(param_value)
    else:
        ret += f'{param_value}'

    if is_multiline:
        ret += '\n'
    ret += '</parameter>\n'

    return ret


def convert_tools_to_description(tools: list[dict]) -> str:
    """Convert tool definitions to text description for non-function-calling models.

    Args:
        tools: List of tool definitions

    Returns:
        Formatted tool description string

    """
    ret = ''
    for i, tool in enumerate(tools):
        assert tool['type'] == 'function'
        fn = tool['function']
        if i > 0:
            ret += '\n'
        ret += f'---- BEGIN FUNCTION #{i + 1}: {fn["name"]} ----\n'
        ret += f'Description: {fn["description"]}\n'
        if 'parameters' in fn:
            ret += 'Parameters:\n'
            properties = fn['parameters'].get('properties', {})
            required_params = set(fn['parameters'].get('required', []))
            for j, (param_name, param_info) in enumerate(properties.items()):
                is_required = param_name in required_params
                param_status = 'required' if is_required else 'optional'
                param_type = param_info.get('type', 'string')
                desc = param_info.get('description', 'No description provided')
                if 'enum' in param_info:
                    enum_values = ', '.join(f'`{v}`' for v in param_info['enum'])
                    desc += f'\nAllowed values: [{enum_values}]'
                ret += (
                    f'  ({j + 1}) {param_name} ({param_type}, {param_status}): {desc}\n'
                )
        else:
            ret += 'No parameters are required for this function.\n'
        ret += f'---- END FUNCTION #{i + 1} ----\n'
    return ret


def _process_system_message(content: Any, system_prompt_suffix: str) -> dict:
    """Process system message by appending the system prompt suffix."""
    from backend.inference._fn_call_to_messages import _raise_unexpected_content_type  # noqa: PLC0415
    if isinstance(content, str):
        content += system_prompt_suffix
    elif isinstance(content, list):
        if content and content[-1]['type'] == 'text':
            content[-1]['text'] += system_prompt_suffix
        else:
            content.append({'type': 'text', 'text': system_prompt_suffix})
    else:
        _raise_unexpected_content_type(content)
    return {'role': 'system', 'content': content}


def _process_user_message(
    content: Any,
    tools: list[dict],
    add_in_context_learning_example: bool,
    first_user_message_encountered: bool,
    mode: str = 'agent',
) -> tuple[dict, bool]:
    """Process user message, adding in-context learning example if needed."""
    if not first_user_message_encountered and add_in_context_learning_example:
        first_user_message_encountered = True
        content = _add_in_context_learning_example(content, tools, mode=mode)

    return ({'role': 'user', 'content': content}, first_user_message_encountered)


def _add_in_context_learning_example(
    content: Any,
    tools: list[dict],
    mode: str = 'agent',
) -> Any:
    """Add in-context learning example to content."""
    from backend.inference._fn_call_to_messages import _raise_unexpected_content_type  # noqa: PLC0415
    if not (example := IN_CONTEXT_LEARNING_EXAMPLE_PREFIX(tools, mode)):
        return content

    if isinstance(content, str):
        return example + content
    if isinstance(content, list):
        return _add_example_to_list_content(content, example)
    _raise_unexpected_content_type(content)


def _add_example_to_list_content(content: list, example: str) -> list:
    """Add example to list content."""
    if content and content[0]['type'] == 'text':
        content[0]['text'] = example + content[0]['text']
    else:
        content.insert(0, {'type': 'text', 'text': example})
    return content

