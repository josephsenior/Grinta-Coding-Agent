"""Plain-text fallback helpers for :class:`Orchestrator`.

The simplified agent protocol is:

* tool call -> execute, continue loop
* ask_user -> pause until the user replies
* plain text -> final response, end the run

This module only covers the last case when the provider response did not
produce parsed tool calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.interaction_modes import normalize_interaction_mode
from backend.core.logger import app_logger as logger
from backend.ledger.action import MessageAction
from backend.ledger.event import EventSource

if TYPE_CHECKING:
    from backend.engine.orchestrator import Orchestrator
    from backend.ledger.action import Action


def _visible_fallback_message_text(message_text: str) -> str:
    from backend.cli.display.tool_call_display import redact_streamed_tool_call_markers

    return redact_streamed_tool_call_markers(message_text or '').strip()


def _protocol_mode_fallback_message(
    _orch: Orchestrator,
    message_text: str,
    reasoning: str,
    _state: object | None,
    *,
    mode: str,
) -> Action:
    """Return a final message for Agent/Plan prose with no tool calls."""
    fallback = MessageAction(
        content=message_text,
        thought=reasoning,
        wait_for_response=False,
        final_response=True,
    )
    fallback.source = EventSource.AGENT
    logger.debug(
        'Plain-text response in %s mode is final under simplified protocol.',
        normalize_interaction_mode(mode),
    )
    return fallback


def _build_fallback_action(orch: Orchestrator, result) -> Action:
    """Create a final message action when parsing produced no durable action."""
    from backend.core.errors import LLMNoActionError

    message_text = ''
    message = None
    if result.response and getattr(result.response, 'choices', None):
        first_choice = result.response.choices[0]
        message = getattr(first_choice, 'message', None)
        if message is not None:
            raw = getattr(message, 'content', '') or ''
            message_text = raw if isinstance(raw, str) else str(raw)

    if not message_text.strip():
        raise LLMNoActionError('LLM returned no tool calls and no content.')
    message_text = _visible_fallback_message_text(message_text)
    if not message_text.strip():
        raise LLMNoActionError(
            'LLM returned only internal tool-call transport markers and no '
            'valid tool action.'
        )

    reasoning = ''
    if message is not None:
        reasoning = getattr(message, 'reasoning_content', '') or ''

    executor = getattr(orch, 'executor', None)
    config = getattr(orch, 'config', None)
    active_mode = normalize_interaction_mode(
        getattr(executor, '_active_run_mode', None),
        default=normalize_interaction_mode(getattr(config, 'mode', 'agent')),
    )
    return _protocol_mode_fallback_message(
        orch,
        message_text,
        reasoning,
        getattr(executor, '_state', None),
        mode=active_mode,
    )
