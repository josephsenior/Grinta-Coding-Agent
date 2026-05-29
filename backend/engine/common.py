from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable
from threading import Lock
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

_LOGGER = logging.getLogger(__name__)

_THINK_TAG_RE = re.compile(
    r'<(?:redacted_thinking|think)>.*?</(?:redacted_thinking|think)>',
    re.DOTALL | re.IGNORECASE,
)

_THINK_INNER_RE = re.compile(
    r'<(?:redacted_thinking|think)>\s*(.*?)\s*</(?:redacted_thinking|think)>',
    re.DOTALL | re.IGNORECASE,
)

_RETRY_GUARD_LOCK = Lock()
_RETRY_GUARD: dict[str, tuple[str, int]] = {}
_RETRY_GUARD_MAX_ENTRIES = 1000
_RETRY_GUARD_MAX_ATTEMPTS = 2


def _compute_content_hash(content: str) -> str:
    """Compute a short hash of content for retry tracking."""
    return hashlib.sha256(content[:4096].encode()).hexdigest()[:16]


def _check_format_error_retry_guard(
    tool_name: str,
    raw_content: str,
    error_signature: str,
) -> tuple[bool, str]:
    """Check if a FORMAT_ERROR should be allowed to retry.

    Returns (should_continue, reason). If should_continue is False, reason
    explains why the retry was blocked.
    """
    key = f'{tool_name}:{error_signature}'
    content_hash = _compute_content_hash(raw_content)
    with _RETRY_GUARD_LOCK:
        if len(_RETRY_GUARD) > _RETRY_GUARD_MAX_ENTRIES:
            _RETRY_GUARD.clear()
        if key in _RETRY_GUARD:
            stored_hash, attempt_count = _RETRY_GUARD[key]
            if stored_hash == content_hash and attempt_count >= _RETRY_GUARD_MAX_ATTEMPTS:
                return False, (
                    f"Retry guard triggered: {tool_name} with identical error "
                    f"'{error_signature}' and same content hash {content_hash} "
                    f"after {attempt_count} attempts. Stop auto-retry and report as "
                    f"system/tool error."
                )
            if stored_hash == content_hash:
                _RETRY_GUARD[key] = (content_hash, attempt_count + 1)
            else:
                _RETRY_GUARD[key] = (content_hash, 1)
        else:
            _RETRY_GUARD[key] = (content_hash, 1)
    return True, ''


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

    When the model emits both native tool_calls and valid pseudo-XML for the
    same code-heavy tool, the XML transport wins and duplicate native calls are
    dropped.  Remaining native calls for code-heavy tools still raise a
    directive error so the model re-emits using the XML format.
    """
    validate_response_choices(response)
    assistant_msg = extract_assistant_message(response)

    native_tool_calls = list(getattr(assistant_msg, 'tool_calls', None) or [])
    content = getattr(assistant_msg, 'content', None)
    content_text = _raw_message_content_text(content)
    text_marker_tool_calls = _extract_text_marker_tool_calls_from_content(content_text)

    # ── Parse pseudo-XML tool calls from content text ────────────────
    xml_tool_calls: list[Any] = []
    if xml_tool_names:
        xml_tool_calls = _extract_xml_tool_calls_from_content(
            content_text, xml_tool_names
        )

    # ── Prefer XML over duplicate native calls ───────────────────────
    if xml_tool_names and native_tool_calls and xml_tool_calls:
        native_tool_calls = _filter_native_tool_calls_superseded_by_xml(
            native_tool_calls, xml_tool_calls, xml_tool_names
        )

    # ── Compliance guard ─────────────────────────────────────────────
    # Reject native tool calls that target code-heavy tools.  These
    # must use the XML transport so code is never JSON-encoded.
    if xml_tool_names and native_tool_calls:
        _enforce_xml_compliance(native_tool_calls, xml_tool_names)

    all_tool_calls = native_tool_calls + text_marker_tool_calls + xml_tool_calls

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


def _tool_call_function_name(tool_call: Any) -> str:
    fn = getattr(tool_call, 'function', None)
    return str(getattr(fn, 'name', '') or '') if fn else ''


def _xml_tools_successfully_parsed(xml_tool_calls: list[Any]) -> set[str]:
    """Return tool names parsed from content XML without syntax errors."""
    names: set[str] = set()
    for tc in xml_tool_calls:
        name = _tool_call_function_name(tc)
        if not name:
            continue
        raw_arguments = getattr(getattr(tc, 'function', None), 'arguments', '') or '{}'
        try:
            arguments = (
                json.loads(raw_arguments)
                if isinstance(raw_arguments, str)
                else raw_arguments
            )
        except json.JSONDecodeError:
            continue
        if isinstance(arguments, dict) and '__xml_syntax_error__' in arguments:
            continue
        names.add(name)
    return names


def _filter_native_tool_calls_superseded_by_xml(
    native_tool_calls: list[Any],
    xml_tool_calls: list[Any],
    xml_tool_names: frozenset[str],
) -> list[Any]:
    """Drop native calls when the same tool was successfully parsed from XML."""
    superseded = _xml_tools_successfully_parsed(xml_tool_calls) & set(xml_tool_names)
    if not superseded:
        return native_tool_calls

    filtered: list[Any] = []
    dropped: set[str] = set()
    for tc in native_tool_calls:
        name = _tool_call_function_name(tc)
        if name in superseded:
            dropped.add(name)
            continue
        filtered.append(tc)

    if dropped:
        logger.info(
            'Ignoring native tool call(s) for %s; valid XML transport present in content',
            sorted(dropped),
        )
    return filtered


def _extract_text_marker_tool_calls_from_content(content_text: str) -> list[Any]:
    if not content_text or 'tool_call' not in content_text and '[Tool call]' not in content_text:
        return []
    from backend.cli.tool_call_display import extract_tool_calls_from_text_markers

    tool_calls = extract_tool_calls_from_text_markers(content_text)
    return [
        _SyntheticToolCall(
            str(tool_call.get('id') or f'text_toolu_{index:02d}'),
            str((tool_call.get('function') or {}).get('name') or ''),
            str((tool_call.get('function') or {}).get('arguments') or '{}'),
        )
        for index, tool_call in enumerate(tool_calls)
        if (tool_call.get('function') or {}).get('name')
    ]


def _enforce_xml_compliance(
    tool_calls: list[Any], xml_tool_names: frozenset[str]
) -> None:
    """Reject native tool calls that should use the XML transport.

    Raises :class:`FunctionCallValidationError` with a clear directive
    telling the model to re-emit the call using the pseudo-XML format.
    Applies retry guard to prevent infinite loops when the same error repeats.
    """
    for tc in tool_calls:
        fn = getattr(tc, 'function', None)
        name = getattr(fn, 'name', '') if fn else ''
        if name in xml_tool_names:
            raw_arguments = getattr(fn, 'arguments', '') or ''
            error_sig = 'native_toolcall_rejected'
            allowed, reason = _check_format_error_retry_guard(name, raw_arguments, error_sig)
            if not allowed:
                _LOGGER.error('FORMAT_ERROR retry guard: %s', reason)
                raise CoreFunctionCallValidationError(
                    f'[FORMAT_ERROR] Retry guard stopped repeated FORMAT_ERROR for '
                    f'tool `{name}` after multiple attempts. This indicates a '
                    f'persistent issue with the tool call format.\n'
                    f'{reason}\n'
                    f'[SYSTEM_ACTION] Report this as a system/tool error.'
                )
            example = _xml_format_error_example(name)
            _LOGGER.warning(
                'FORMAT_ERROR: Tool %s sent via native tool call instead of XML. '
                'Arguments preview: %s...',
                name,
                raw_arguments[:200],
            )
            raise CoreFunctionCallValidationError(
                f'[FORMAT_ERROR] Tool `{name}` must use the XML format, not '
                f'the standard tool calling format.\n'
                f'[CAUSE] The tool call was sent through JSON function calling, '
                f'but `{name}` requires the pseudo-XML format so code payloads '
                f'are not JSON-encoded.\n'
                f'[ACTION] Re-emit this call using the XML format exactly like this:\n'
                f'{example}\n'
                f'[FORMAT] Type rules for XML parameters:\n'
                f'  - Integer params (start_line, end_line, insert_line): bare numbers (e.g. 7)\n'
                f'  - Array params (view_range, file_edits, edits): JSON arrays (e.g. [1, 10])\n'
                f'  - Boolean params (overwrite_existing): true or false (lowercase)\n'
                f'  - String params (content, path, symbol_name): raw text between tags\n'
            )


def _xml_format_error_example(tool_name: str) -> str:
    return (
        f'  <function={tool_name}>\n'
        f'  <parameter=command>command_name</parameter>\n'
        f'  <parameter=security_risk>LOW</parameter>\n'
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
    seen_tool_names: set[str] = set()

    pos = 0
    while pos < len(content_text):
        open_m = _FN_OPEN_RE.search(content_text, pos)
        if open_m is None:
            break

        fn_name = (open_m.group(1) or '').strip()
        if fn_name not in xml_tool_names:
            pos = open_m.end(0)
            continue

        # Reject multiple XML blocks for the same tool in one response.
        # Each tool should be emitted once per response.
        if fn_name in seen_tool_names:
            logger.warning(
                'Multiple <function=%s> blocks detected in single response. '
                'Only the first occurrence is processed; subsequent ones are ignored.',
                fn_name,
            )
            pos = open_m.end(0)
            continue
        seen_tool_names.add(fn_name)

        close_m = _FN_CLOSE_RE.search(content_text, open_m.end(0))
        if close_m is None:
            logger.warning(
                'Unclosed <function=%s> block in response content', fn_name
            )
            fn_body = content_text[open_m.end(0) :]
            end_pos = len(content_text)
            is_unclosed = True
        else:
            fn_body = content_text[open_m.end(0) : close_m.start(0)]
            end_pos = close_m.end(0)
            is_unclosed = False

        # Extract parameters with schema-aware type coercion and validation
        try:
            from backend.inference.fn_call_converter import (
                _extract_and_validate_params as _validate_xml_params,
            )

            tool_def = None
            param_body = fn_body
            param_matches = list(_iter_parameter_matches(fn_body, param_body))

            # Fallback: raw string extraction for unknown tools
            params = {}
            for pm in param_matches:
                    pn = pm.group(1)
                    pv = pm.group(2)
                    if pv.startswith(chr(10)):
                        pv = pv[1:]
                    if pv.endswith(chr(10)):
                        pv = pv[:-1]
                    params[pn] = pv

            if is_unclosed:
                params['__xml_syntax_error__'] = 'Unclosed <function> tag. Use </function> to close.'
            elif not params and fn_body.strip():
                params['__xml_syntax_error__'] = 'No <parameter=...> tags found. You must wrap arguments in parameter tags.'

            # Check retry guard for XML syntax errors
            if '__xml_syntax_error__' in params:
                serialized_args = json.dumps(params, sort_keys=True, ensure_ascii=False)
                error_sig = f"xml_parsing:{params['__xml_syntax_error__']}"
                allowed, reason = _check_format_error_retry_guard(fn_name, serialized_args, error_sig)
                if not allowed:
                    _LOGGER.error('XML parsing retry guard: %s', reason)
                    params = {
                        '__xml_syntax_error__': f"Retry guard stopped repeated error: {params['__xml_syntax_error__']}. Report as system error."
                    }

        except Exception as e:
            logger.warning(
                'Failed to parse parameters for <function=%s>: %s',
                fn_name,
                e,
            )
            params = {
                '__xml_syntax_error__': f'Malformed parameters: {str(e)}'
            }

        call_id = f'xml_toolu_{call_counter:02d}'
        call_counter += 1

        # Package as JSON arguments string for compatibility with
        # parse_tool_call_arguments downstream.
        arguments_json = json.dumps(params, ensure_ascii=False)
        results.append(_SyntheticToolCall(call_id, fn_name, arguments_json))

        pos = end_pos

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
