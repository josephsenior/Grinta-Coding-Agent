from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

_THINK_TAG_RE = re.compile(r'<think>.*?</think>', re.DOTALL | re.IGNORECASE)


def strip_thinking_tags(text: str) -> str:
    """Remove <think>...</think> blocks emitted by reasoning models (e.g. MiniMax, DeepSeek R1).

    These blocks contain chain-of-thought that should not appear in the final
    user-facing response.  The surrounding whitespace is collapsed so the
    result reads cleanly.
    """
    stripped = _THINK_TAG_RE.sub('', text)
    return re.sub(r'\n{3,}', '\n\n', stripped).strip()

from backend.core.logger import app_logger as logger
from backend.inference.tool_types import make_function_chunk, make_tool_param
from backend.ledger.action import Action

if TYPE_CHECKING:
    from backend.engine.contracts import ChatCompletionToolParam
    from backend.engine.executor import ModelResponse
    from backend.ledger.serialization.event import ToolCallMetadata


class FunctionCallValidationError(Exception):
    """Raised when an LLM response fails validation for function calling."""


class FunctionCallNotExistsError(FunctionCallValidationError):
    """Raised when a model attempts to call a tool that does not exist."""


def validate_response_choices(response: ModelResponse) -> None:
    """Validate that response has exactly one choice."""
    assert len(response.choices) == 1, 'Only one choice is supported for now'


def extract_assistant_message(response: ModelResponse) -> Any:
    """Extract assistant message from model response."""
    if not getattr(response, 'choices', None) or len(response.choices) == 0:
        raise FunctionCallValidationError('Model response has no choices')
    choice = response.choices[0]
    assistant_msg = getattr(choice, 'message', None)
    if assistant_msg is None:
        raise FunctionCallValidationError(
            'Model response choice is missing a message payload'
        )
    return assistant_msg


def set_response_id_for_actions(actions: list[Action], response: ModelResponse) -> None:
    """Set the response ID for a list of actions."""
    if not actions:
        raise FunctionCallValidationError(
            'set_response_id_for_actions requires a non-empty actions list'
        )
    for action in actions:
        action.response_id = response.id


def parse_tool_call_arguments(tool_call: Any) -> dict[str, Any]:
    """Parse tool call arguments from JSON string to dictionary."""
    try:
        if isinstance(tool_call.function.arguments, dict):
            return tool_call.function.arguments
        return json.loads(tool_call.function.arguments)
    except (json.JSONDecodeError, AttributeError) as e:
        msg = f'Failed to parse tool call arguments: {e}. Raw arguments: {tool_call.function.arguments}'
        raise FunctionCallValidationError(msg) from e


def build_tool_call_metadata(
    function_name: str,
    tool_call_id: str,
    response_obj: ModelResponse,
    total_calls_in_response: int,
) -> ToolCallMetadata:
    """Build standardized tool call metadata."""
    from backend.ledger.serialization.event import ToolCallMetadata

    return ToolCallMetadata.from_sdk(
        function_name=function_name,
        tool_call_id=tool_call_id,
        response_obj=response_obj,
        total_calls_in_response=total_calls_in_response,
    )


def extract_thought_from_message(assistant_msg: Any) -> str:
    """Extract thought text from assistant message content."""
    content = getattr(assistant_msg, 'content', None)
    return _coerce_message_content_text(content)


def _coerce_message_content_text(content: Any) -> str:
    """Coerce provider-specific message content shapes into plain text.

    Supports:
    - ``str``
    - ``list[str]``
    - ``list[dict]`` with ``{"text": ...}`` (any ``type``)
    - ``dict`` with ``{"text": ...}``

    ``<think>...</think>`` blocks emitted by reasoning models are stripped so
    they never appear in the user-facing response.
    """
    if content is None:
        return ''
    if isinstance(content, str):
        return strip_thinking_tags(content)
    if isinstance(content, dict):
        text = content.get('text')
        return strip_thinking_tags(text) if isinstance(text, str) else ''
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                if item:
                    parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get('text')
                if isinstance(text, str) and text:
                    parts.append(text)
        return strip_thinking_tags(''.join(parts))
    return ''


def process_tool_calls(
    assistant_msg: Any,
    response: ModelResponse,
    create_action_fn: Callable[[Any, dict[str, Any]], Action],
    extract_thought_fn: Callable[[str | None], str],
    combine_thought_fn: Callable[[Action, str], Action],
) -> list[Action]:
    """Common logic for processing tool calls and converting them to actions."""
    actions: list[Action] = []
    thought = extract_thought_fn(getattr(assistant_msg, 'content', None))

    for i, tool_call in enumerate(assistant_msg.tool_calls):
        logger.debug('Processing tool call: %s', tool_call)
        arguments = parse_tool_call_arguments(tool_call)
        action = create_action_fn(tool_call, arguments)

        # Add thought to first action
        if i == 0:
            action = combine_thought_fn(action, thought)

        # Add tool call metadata
        action.tool_call_metadata = build_tool_call_metadata(
            function_name=tool_call.function.name,
            tool_call_id=tool_call.id,
            response_obj=response,
            total_calls_in_response=len(assistant_msg.tool_calls),
        )

        actions.append(action)

    return actions


def common_response_to_actions(
    response: ModelResponse,
    create_action_fn: Callable[[Any, dict[str, Any]], Action],
    combine_thought_fn: Callable[[Action, str], Action],
    mcp_tool_names: list[str] | None = None,
) -> list[Action]:
    """Common implementation for converting model response to actions."""
    validate_response_choices(response)
    assistant_msg = extract_assistant_message(response)

    tool_calls = getattr(assistant_msg, 'tool_calls', None)
    if tool_calls:
        # Pass mcp_tool_names through tool_call object for the factory function
        for tc in tool_calls:
            setattr(tc, '_mcp_tool_names', mcp_tool_names)

        actions = process_tool_calls(
            assistant_msg,
            response,
            create_action_fn,
            lambda _: extract_thought_from_message(assistant_msg),
            combine_thought_fn,
        )
    else:
        content = getattr(assistant_msg, 'content', None)
        text_content = _coerce_message_content_text(content)
        from backend.ledger.action import MessageAction

        actions = [MessageAction(content=text_content, wait_for_response=True)]

    set_response_id_for_actions(actions, response)
    return actions


def create_tool_definition(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
    additional_properties: bool = False,
) -> ChatCompletionToolParam:
    """Create a standardized tool definition."""
    return make_tool_param(
        type='function',
        function=make_function_chunk(
            name=name,
            description=description,
            parameters={
                'type': 'object',
                'properties': properties,
                'required': required,
                'additionalProperties': additional_properties,
            },
        ),
    )


def get_common_path_param(description: str | None = None) -> dict[str, Any]:
    """Get common path parameter definition."""
    return {
        'type': 'string',
        'description': description or 'Absolute path to file or directory.',
    }


def get_common_pattern_param(description: str) -> dict[str, Any]:
    """Get common pattern parameter definition."""
    return {
        'type': 'string',
        'description': description,
    }


def get_common_timeout_param(
    description: str = 'Optional timeout in seconds.',
) -> dict[str, Any]:
    """Get a standardized timeout parameter definition."""
    return {
        'type': 'number',
        'description': description,
    }
