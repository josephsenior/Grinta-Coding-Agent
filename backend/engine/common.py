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

_THINK_TAG_RE = re.compile(
    r'<(?:redacted_thinking|think)>.*?</(?:redacted_thinking|think)>',
    re.DOTALL | re.IGNORECASE,
)

_THINK_INNER_RE = re.compile(
    r'<(?:redacted_thinking|think)>\s*(.*?)\s*</(?:redacted_thinking|think)>',
    re.DOTALL | re.IGNORECASE,
)


def extract_redacted_thinking_inner(text: str) -> str:
    """Return inner text of all ``<redacted_thinking>`` / ``<think>`` blocks."""
    parts = [
        m.group(1).strip()
        for m in _THINK_INNER_RE.finditer(text or '')
        if m.group(1).strip()
    ]
    return '\n\n'.join(parts)


def strip_thinking_tags(text: str) -> str:
    """Remove ``<redacted_thinking>`` and ``<think>`` blocks from text.

    Covers Anthropic/MiniMax (``<redacted_thinking>``), DeepSeek R1, QwQ,
    Ollama reasoning models, and early OpenAI o-series (``<think>``).
    The surrounding whitespace is collapsed so the result reads cleanly.
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
        if isinstance(preview, str):
            if len(preview) > 240:
                preview = f'{str(preview)[:237]}...'
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
    reasoning_content = getattr(assistant_msg, 'reasoning_content', None)
    if reasoning_content:
        return reasoning_content.strip()
    raw = _raw_message_content_text(getattr(assistant_msg, 'content', None))
    return extract_redacted_thinking_inner(raw).strip()


def _message_content_text_part(item: Any) -> str:
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return ''
    text = item.get('text')
    return text if isinstance(text, str) else ''


def _join_message_content_text_parts(content: list[Any]) -> str:
    parts: list[str] = []
    for item in content:
        if text := _message_content_text_part(item):
            parts.append(text)
    return ''.join(parts)


def _raw_message_content_text(content: Any) -> str:
    """Like :func:`_coerce_message_content_text` but leaves tags intact."""
    if content is None:
        return ''
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return _message_content_text_part(content)
    if isinstance(content, list):
        return _join_message_content_text_parts(content)
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


def _canonicalize_tool_call_arguments(
    tool_call: Any, arguments: dict[str, Any]
) -> None:
    r"""Overwrite ``tool_call.function.arguments`` with canonical JSON.

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
        fn.arguments = canonical
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
    xml_tool_names: frozenset[str] | None = None,
) -> list[Action]:
    """Common implementation for converting model response to actions.

    Supports hybrid tool calling: native provider tool_calls for simple
    tools **plus** pseudo-XML ``<function=...>`` blocks in response content
    for code-heavy tools (editors).  The ``xml_tool_names`` parameter
    lists tool names expected via the XML transport.

    A compliance guard rejects native tool calls for code-heavy tools,
    returning a directive error that tells the model to re-emit using
    the XML format.
    """
    validate_response_choices(response)
    assistant_msg = extract_assistant_message(response)

    native_tool_calls = list(getattr(assistant_msg, 'tool_calls', None) or [])

    # ── Compliance guard ─────────────────────────────────────────────
    # Reject native tool calls that target code-heavy tools.  These
    # must use the XML transport so code is never JSON-encoded.
    if xml_tool_names and native_tool_calls:
        _enforce_xml_compliance(native_tool_calls, xml_tool_names)

    # ── Parse pseudo-XML tool calls from content text ────────────────
    xml_tool_calls: list[Any] = []
    if xml_tool_names:
        content = getattr(assistant_msg, 'content', None)
        content_text = _raw_message_content_text(content)
        xml_tool_calls = _extract_xml_tool_calls_from_content(
            content_text, xml_tool_names
        )

    all_tool_calls = native_tool_calls + xml_tool_calls

    if all_tool_calls:
        # Pass mcp_tool_names through tool_call object for the factory function
        for tc in all_tool_calls:
            if not hasattr(tc, '_mcp_tool_names'):
                tc._mcp_tool_names = mcp_tool_names
            else:
                tc._mcp_tool_names = mcp_tool_names

        # Replace the tool_calls on the assistant message so
        # process_tool_calls sees the merged list.
        assistant_msg.tool_calls = all_tool_calls

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
        cot = extract_redacted_thinking_inner(
            _raw_message_content_text(content)
        ).strip()
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


def _enforce_xml_compliance(
    tool_calls: list[Any], xml_tool_names: frozenset[str]
) -> None:
    """Reject native tool calls that should use the XML transport.

    Raises :class:`FunctionCallValidationError` with a clear directive
    telling the model to re-emit the call using the pseudo-XML format.
    """
    for tc in tool_calls:
        fn = getattr(tc, 'function', None)
        name = getattr(fn, 'name', '') if fn else ''
        if name in xml_tool_names:
            raise CoreFunctionCallValidationError(
                f'[FORMAT_ERROR] Tool `{name}` must use the XML format, not '
                f'the standard tool calling format.\n'
                f'[CAUSE] The tool call was sent through JSON function calling, '
                f'but `{name}` requires the pseudo-XML format so code payloads '
                f'are not JSON-encoded.\n'
                f'[ACTION] Re-emit this call using the XML format:\n'
                f'  <function={name}>\n'
                f'  <parameter=command>your_command</parameter>\n'
                f'  <parameter=path>/path/to/file</parameter>\n'
                f'  <parameter=new_code>\n'
                f'  your code here — raw text, no escaping\n'
                f'  </parameter>\n'
                f'  </function>'
            )


class _SyntheticFunction:
    """Lightweight stand-in for ``tool_call.function`` on XML-parsed calls."""

    __slots__ = ('name', 'arguments')

    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _SyntheticToolCall:
    """Lightweight stand-in for a native tool_call object."""

    __slots__ = ('id', 'type', 'function', '_mcp_tool_names')

    def __init__(self, call_id: str, name: str, arguments: str) -> None:
        self.id = call_id
        self.type = 'function'
        self.function = _SyntheticFunction(name, arguments)
        self._mcp_tool_names: list[str] | None = None


def _extract_xml_tool_calls_from_content(
    content_text: str, xml_tool_names: frozenset[str]
) -> list[Any]:
    """Parse pseudo-XML ``<function=...>`` blocks from response content.

    Returns a list of :class:`_SyntheticToolCall` objects compatible with
    the native tool_call interface so they can be processed through the
    same ``process_tool_calls`` pipeline.
    """
    if not content_text or '<function' not in content_text:
        return []

    from backend.inference.fn_call_converter import (
        _FN_CLOSE_RE,
        _FN_OPEN_RE,
        _iter_parameter_matches,
    )

    results: list[Any] = []
    call_counter = 0

    pos = 0
    while pos < len(content_text):
        open_m = _FN_OPEN_RE.search(content_text, pos)
        if open_m is None:
            break

        fn_name = (open_m.group(1) or '').strip()
        if fn_name not in xml_tool_names:
            pos = open_m.end(0)
            continue

        close_m = _FN_CLOSE_RE.search(content_text, open_m.end(0))
        if close_m is None:
            logger.warning(
                'Unclosed <function=%s> block in response content', fn_name
            )
            break

        fn_body = content_text[open_m.end(0) : close_m.start(0)]

        # Extract parameters as raw text — the key advantage of XML transport
        try:
            params: dict[str, Any] = {}
            for pm in _iter_parameter_matches(fn_body):
                param_name = pm.group(1)
                param_value = pm.group(2)
                # Strip exactly one leading/trailing newline from multiline
                # values (the XML format adds them for readability).
                if param_value.startswith('\n'):
                    param_value = param_value[1:]
                if param_value.endswith('\n'):
                    param_value = param_value[:-1]
                params[param_name] = param_value
        except Exception as e:
            logger.warning(
                'Failed to parse parameters for <function=%s>: %s',
                fn_name,
                e,
            )
            pos = close_m.end(0)
            continue

        call_id = f'xml_toolu_{call_counter:02d}'
        call_counter += 1

        # Package as JSON arguments string for compatibility with
        # parse_tool_call_arguments downstream.
        arguments_json = json.dumps(params, ensure_ascii=False)
        results.append(_SyntheticToolCall(call_id, fn_name, arguments_json))

        pos = close_m.end(0)

    return results


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
