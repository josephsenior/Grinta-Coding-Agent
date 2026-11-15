"""Markers for application-owned context that varies between agent turns."""

from __future__ import annotations

import re
from typing import Any

TURN_CONTEXT_START = '<GRINTA_TURN_CONTEXT'
TURN_CONTEXT_END = '</GRINTA_TURN_CONTEXT>'

_KIND_PATTERN = re.compile(r'[^a-z0-9_-]+')


def is_turn_context_text(text: object) -> bool:
    """Return whether *text* is an application-owned per-turn context block."""
    return isinstance(text, str) and text.lstrip().startswith(TURN_CONTEXT_START)


def wrap_turn_context(text: object, *, kind: str) -> str:
    """Wrap dynamic context without changing an already wrapped block.

    The marker lets prompt assembly preserve each dynamic snapshot beside the
    user turn it originally accompanied. Provider adapters can also distinguish
    these blocks from the stable leading system instruction.
    """
    value = '' if text is None else str(text)
    if is_turn_context_text(value):
        return value
    safe_kind = _KIND_PATTERN.sub('-', kind.strip().lower()).strip('-') or 'context'
    return (
        f'<GRINTA_TURN_CONTEXT kind="{safe_kind}">\n{value.strip()}\n{TURN_CONTEXT_END}'
    )


def _content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return '' if content is None else str(content)
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and item.get('text'):
            parts.append(str(item['text']))
    return '\n'.join(parts)


def _prepend_context(message: dict[str, Any], context: str) -> dict[str, Any]:
    merged = dict(message)
    content = message.get('content', '')
    if isinstance(content, list):
        merged['content'] = [{'type': 'text', 'text': context}, *content]
    else:
        text = content if isinstance(content, str) else str(content or '')
        merged['content'] = f'{context}\n\n{text}' if text else context
    return merged


def _is_stable_system_message(role: object, text: str, leading: bool) -> bool:
    return leading and role == 'system' and not is_turn_context_text(text)


def _append_provider_system_context(
    message: dict[str, Any],
    text: str,
    pending_context: list[str],
) -> bool:
    if message.get('role') != 'system':
        return False
    if text:
        pending_context.append(wrap_turn_context(text, kind='provider-system'))
    return True


def _append_message_with_pending_context(
    message: dict[str, Any],
    pending_context: list[str],
    body: list[dict[str, Any]],
) -> None:
    if pending_context:
        context = '\n\n'.join(pending_context)
        pending_context.clear()
        if message.get('role') == 'user':
            body.append(_prepend_context(message, context))
            return
        body.append({'role': 'user', 'content': context})
    body.append(message)


def split_stable_system_prefix(
    messages: list[dict[str, Any]],
) -> tuple[list[str], list[dict[str, Any]]]:
    """Split stable leading instructions and merge late context into its user turn.

    Provider APIs that expose only one top-level system instruction cannot keep
    mid-conversation system roles. Merging app-owned context into the following
    user turn preserves ordering without producing malformed consecutive user
    entries in providers that expect alternating chat roles.
    """
    stable_system: list[str] = []
    body: list[dict[str, Any]] = []
    pending_context: list[str] = []
    leading = True

    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get('role')
        text = _content_to_text(message.get('content')).strip()
        if _is_stable_system_message(role, text, leading):
            if text:
                stable_system.append(text)
            continue

        leading = False
        if _append_provider_system_context(message, text, pending_context):
            continue

        _append_message_with_pending_context(message, pending_context, body)

    if pending_context:
        body.append({'role': 'user', 'content': '\n\n'.join(pending_context)})
    return stable_system, body
