"""Shared response parsing helpers for the orchestrator executor."""

from __future__ import annotations

from typing import Any

from backend.ledger.action import Action


def without_blank_agent_messages(actions: list[Action]) -> list[Action]:
    """Drop agent ``MessageAction``s with nothing user-visible."""
    from backend.ledger.action import MessageAction

    out: list[Action] = []
    for action in actions:
        if isinstance(action, MessageAction):
            content = str(getattr(action, 'content', '') or '').strip()
            thought = str(getattr(action, 'thought', '') or '').strip()
            if not content and not thought:
                continue
        out.append(action)
    return out


def is_recoverable_tool_call_error(exc: Exception) -> bool:
    """Return True when error came from malformed or invalid LLM tool output."""
    from backend.core.errors import (
        FunctionCallConversionError,
        LLMMalformedActionError,
    )
    from backend.core.errors import (
        FunctionCallNotExistsError as CoreFunctionCallNotExistsError,
    )
    from backend.core.errors import (
        FunctionCallValidationError as CoreFunctionCallValidationError,
    )
    from backend.core.tool_arguments_json import TruncatedToolArgumentsError
    from backend.engine.common import (
        FunctionCallNotExistsError as CommonFunctionCallNotExistsError,
    )
    from backend.engine.common import (
        FunctionCallValidationError as CommonFunctionCallValidationError,
    )

    return isinstance(
        exc,
        (
            CoreFunctionCallValidationError,
            CoreFunctionCallNotExistsError,
            FunctionCallConversionError,
            LLMMalformedActionError,
            CommonFunctionCallValidationError,
            CommonFunctionCallNotExistsError,
            TruncatedToolArgumentsError,
        ),
    )


def build_recoverable_tool_call_error_action(exc: Exception) -> Action:
    """Create a recovery action that feeds precise correction guidance back to the LLM."""
    from backend.core.tool_arguments_json import TruncatedToolArgumentsError
    from backend.ledger.action import AgentThinkAction

    if isinstance(exc, TruncatedToolArgumentsError):
        return AgentThinkAction(
            thought=(
                '[TOOL_CALL_TRUNCATED] The previous tool call arguments were '
                'stream-truncated — the JSON object was never closed, meaning '
                'the model stopped generating before finishing the payload. '
                'This commonly happens with very large file bodies. '
                'Please re-issue the same tool call with the complete, valid '
                'JSON arguments. If the file body is very large, consider '
                'splitting it: create a minimal stub first, then extend with '
                'insert_text or edit_mode calls.'
            )
        )

    detail = str(exc).strip() or exc.__class__.__name__
    if len(detail) > 1200:
        detail = f'{detail[:1200]}...'

    return AgentThinkAction(
        thought=(
            '[TOOL_CALL_RECOVERABLE_ERROR] The previous tool call was invalid and was not executed. '
            f'Details: {detail}\n'
            'Recover by emitting one corrected tool call with strict JSON arguments: '
            'use double-quoted keys/strings, escape embedded newlines/quotes, include required arguments, '
            'and call an existing tool name only.'
        )
    )


def extract_response_text(response: Any) -> str:
    if not hasattr(response, 'choices') or not response.choices:
        return ''
    choice = response.choices[0]
    if not hasattr(choice, 'message'):
        return ''
    content = getattr(choice.message, 'content', None)
    return content_to_str(content)


def _content_text_part(item: Any) -> str:
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return ''
    text = item.get('text')
    return text if isinstance(text, str) else ''


def _join_content_text_parts(content: list[Any]) -> str:
    parts: list[str] = []
    for item in content:
        if text := _content_text_part(item):
            parts.append(text)
    return ''.join(parts)


def content_to_str(content: Any) -> str:
    """Convert message content (str, list of parts, etc.) to a plain string."""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return _content_text_part(content)
    if isinstance(content, list):
        return _join_content_text_parts(content)
    return str(content) if content else ''


def extract_last_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        role = str(message.get('role', ''))
        content = message.get('content', '')
        if role != 'user':
            continue
        return content_to_str(content).strip()
    return ''


def extract_recent_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        role = str(message.get('role', ''))
        content = message.get('content', '')
        if role != 'user':
            continue
        if text := content_to_str(content).strip():
            return text
    return ''
