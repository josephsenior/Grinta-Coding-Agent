from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from backend.core.errors import (
    FunctionCallNotExistsError as CoreFunctionCallNotExistsError,
)
from backend.core.errors import (
    FunctionCallValidationError as CoreFunctionCallValidationError,
)
from backend.core.logger import app_logger as logger
from backend.core.tool_arguments_json import parse_tool_arguments_object
from backend.inference.tool_types import make_function_chunk, make_tool_param
from backend.ledger.action import Action

_THINK_TAG_RE = re.compile(r'<redacted_thinking>.*?</redacted_thinking>', re.DOTALL | re.IGNORECASE)

_THINK_INNER_RE = re.compile(
    r'<redacted_thinking>\s*(.*?)\s*</redacted_thinking>',
    re.DOTALL | re.IGNORECASE,
)


def extract_redacted_thinking_inner(text: str) -> str:
    """Return inner text of all ``<redacted_thinking>...</redacted_thinking>`` blocks."""
    parts = [
        m.group(1).strip()
        for m in _THINK_INNER_RE.finditer(text or '')
        if m.group(1).strip()
    ]
    return '\n\n'.join(parts)


def strip_thinking_tags(text: str) -> str:
    """Remove <redacted_thinking>...</redacted_thinking> blocks emitted by reasoning models (e.g. MiniMax, DeepSeek R1).

    These blocks contain chain-of-thought that should not appear in the final
    user-facing response.  The surrounding whitespace is collapsed so the
    result reads cleanly.
    """
    stripped = _THINK_TAG_RE.sub('', text)
    return re.sub(r'\n{3,}', '\n\n', stripped).strip()

if TYPE_CHECKING:
    from backend.engine.contracts import ChatCompletionToolParam
    from backend.engine.executor import ModelResponse
    from backend.ledger.serialization.event import ToolCallMetadata


class FunctionCallValidationError(CoreFunctionCallValidationError):
    """Raised when an LLM response fails validation for function calling."""


class FunctionCallNotExistsError(
    CoreFunctionCallNotExistsError,
    FunctionCallValidationError,
):
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
    raw_arguments: Any = None
    try:
        raw_arguments = tool_call.function.arguments
        if isinstance(raw_arguments, dict):
            return raw_arguments
        if not isinstance(raw_arguments, str):
            msg = (
                'Tool call arguments must be a JSON string or dict. '
                f'Got {type(raw_arguments).__name__}.'
            )
            raise TypeError(msg)
        return parse_tool_arguments_object(raw_arguments)
    except (AttributeError, TypeError, ValueError) as e:
        preview = raw_arguments
        if isinstance(preview, str) and len(preview) > 240:
            preview = f'{preview[:237]}...'
        msg = f'Failed to parse tool call arguments: {e}. Raw arguments: {preview}'
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
    """LLM thinking tokens only: inner ``<redacted_thinking>...</redacted_thinking>`` text.

    Plain ``message.content`` without those tags is not treated as thinking — nothing
    is merged into ``action.thought`` (no duplicate command lines in the CLI).
    """
    raw = _raw_message_content_text(getattr(assistant_msg, 'content', None))
    return extract_redacted_thinking_inner(raw).strip()


def _raw_message_content_text(content: Any) -> str:
    """Like :func:`_coerce_message_content_text` but leaves tags intact."""
    if content is None:
        return ''
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        text = content.get('text')
        return text if isinstance(text, str) else ''
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
        return ''.join(parts)
    return ''


def _coerce_message_content_text(content: Any) -> str:
    """Coerce provider-specific message content shapes into plain text.

    Supports:
    - ``str``
    - ``list[str]``
    - ``list[dict]`` with ``{"text": ...}`` (any ``type``)
    - ``dict`` with ``{"text": ...}``

    ``<redacted_thinking>...</redacted_thinking>`` blocks emitted by reasoning models are stripped so
    they never appear in the user-facing response.
    """
    return strip_thinking_tags(_raw_message_content_text(content))


def _canonicalize_tool_call_arguments(tool_call: Any, arguments: dict[str, Any]) -> None:
    """Overwrite ``tool_call.function.arguments`` with canonical JSON.

    The raw wire-format string the LLM emitted can contain malformed escape
    sequences (e.g. ``\\y`` or an unterminated ``\\``) that are tolerated by
    our local ``json_repair`` pass but are rejected by upstream APIs when the
    same conversation is replayed (``BadRequestError: Invalid \\escape``). By
    replacing the raw string with ``json.dumps`` of the already-parsed dict we
    guarantee every future turn sends valid JSON, and we also normalize
    ``NaN``/``Infinity`` out (``allow_nan=False``).
    """
    try:
        canonical = json.dumps(arguments, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        logger.debug(
            'Skipping tool-call argument canonicalization (%s): %s',
            type(exc).__name__,
            exc,
        )
        return

    fn = getattr(tool_call, 'function', None)
    if fn is None:
        return
    try:
        setattr(fn, 'arguments', canonical)
    except (AttributeError, TypeError):
        # Some SDK objects are frozen dataclasses / BaseModel with no setattr
        # hook. In that case the caller relies on build_tool_call_metadata
        # copying the already-parsed dict, so the canonical form is preserved
        # downstream through ToolCallMetadata.from_sdk.
        logger.debug(
            'Tool call function is immutable; canonical arguments will be '
            'applied via ToolCallMetadata instead.'
        )


def process_tool_calls(
    assistant_msg: Any,
    response: ModelResponse,
    create_action_fn: Callable[[Any, dict[str, Any]], Action],
    extract_thought_fn: Callable[[Any], str],
    combine_thought_fn: Callable[[Action, str], Action],
) -> list[Action]:
    """Common logic for processing tool calls and converting them to actions."""
    actions: list[Action] = []
    thought = extract_thought_fn(assistant_msg)

    for i, tool_call in enumerate(assistant_msg.tool_calls):
        logger.debug('Processing tool call: %s', tool_call)
        arguments = parse_tool_call_arguments(tool_call)
        # Replace the raw LLM-emitted JSON string with a canonical, round-trip
        # safe re-serialization so malformed escapes never poison replayed
        # conversation history (see BadRequestError: Invalid \escape).
        _canonicalize_tool_call_arguments(tool_call, arguments)
        action = create_action_fn(tool_call, arguments)

        # Attach thinking tokens to first tool call only when the model emitted them.
        if i == 0 and thought:
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

    if tool_calls := getattr(assistant_msg, 'tool_calls', None):
        # Pass mcp_tool_names through tool_call object for the factory function
        for tc in tool_calls:
            setattr(tc, '_mcp_tool_names', mcp_tool_names)

        actions = process_tool_calls(
            assistant_msg,
            response,
            create_action_fn,
            extract_thought_from_message,
            combine_thought_fn,
        )
    else:
        content = getattr(assistant_msg, 'content', None)
        text_content = _coerce_message_content_text(content)
        cot = extract_redacted_thinking_inner(_raw_message_content_text(content)).strip()
        from backend.ledger.action import MessageAction

        actions = [
            MessageAction(
                content=text_content,
                thought=cot,
                wait_for_response=bool(text_content.strip()),
            )
        ]

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
