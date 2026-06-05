"""Protocol-mode fallback and message synthesis for :class:`Orchestrator`.

When the LLM returns prose instead of a tool call, the orchestrator must
choose what to emit: a status card, an abandoned-retry prompt, a
synthesized finish action, or a yield-to-user message. The functions here
encapsulate that policy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.agent_protocol import (
    ABANDONED_RETRY_PROMPT,
    CONTINUATION_NUDGE,
    increment_prose_attempts,
    is_protocol_mode,
    mark_abandoned,
    prose_attempts,
    reset_prose_attempts,
    set_pending_directive,
    tracker_created,
    tracker_terminal,
    work_remains,
)
from backend.core.interaction_modes import normalize_interaction_mode
from backend.core.logger import app_logger as logger
from backend.ledger.action import MessageAction, PlaybookFinishAction
from backend.ledger.event import EventSource

if TYPE_CHECKING:
    from backend.engine.orchestrator import Orchestrator
    from backend.ledger.action import Action


def _visible_fallback_message_text(message_text: str) -> str:
    from backend.cli.tool_call_display import redact_streamed_tool_call_markers

    return redact_streamed_tool_call_markers(message_text or '').strip()


def _synthesize_plain_text_finish(
    message_text: str, *, mode: str
) -> PlaybookFinishAction:
    clean = (message_text or '').strip() or 'All tracked tasks are complete.'
    finish_mode = normalize_interaction_mode(mode)
    return PlaybookFinishAction(
        final_thought=clean,
        outputs={
            'mode': finish_mode,
            'status': 'completed',
            'response': clean,
            'summary': clean,
            'sections': [{'title': 'Summary', 'items': [clean]}],
            'evidence': {
                'status': 'not_applicable',
                'details': 'Synthesized from plain text after tracker completion.',
            },
            'open_items': [],
            'next_step': '',
            'actions_taken': [],
            'verification': {
                'status': 'not_run',
                'details': 'No separate verification was reported in the final text.',
            },
            'remaining_items': [],
        },
    )


def _protocol_mode_fallback_message(
    orch: Orchestrator,
    message_text: str,
    reasoning: str,
    state: object | None,
    *,
    mode: str,
) -> Action:
    """Handle Agent/Plan prose when no parsed action was produced."""
    if not tracker_created(state):
        reset_prose_attempts(state)
        fallback = MessageAction(
            content=message_text, thought=reasoning, wait_for_response=True
        )
        fallback.source = EventSource.AGENT
        return fallback

    if tracker_terminal(state):
        reset_prose_attempts(state)
        return _synthesize_plain_text_finish(message_text, mode=mode)

    if not work_remains(state):
        reset_prose_attempts(state)
        fallback = MessageAction(
            content=message_text, thought=reasoning, wait_for_response=True
        )
        fallback.source = EventSource.AGENT
        return fallback

    current_attempts = prose_attempts(state)
    if current_attempts >= 3:
        mark_abandoned(state)
        logger.warning(
            'Agent/Plan protocol abandoned fallback prose while work remained '
            '(attempts=%d, text=%r).',
            current_attempts,
            message_text[:500],
        )
        abandoned = MessageAction(
            content=ABANDONED_RETRY_PROMPT,
            thought=reasoning,
            wait_for_response=True,
        )
        abandoned.protocol_abandoned = True
        abandoned.source = EventSource.AGENT
        return abandoned

    count = increment_prose_attempts(state)
    if hasattr(executor := getattr(orch, 'executor', None), '_consecutive_plain_text_blocks'):
        executor._consecutive_plain_text_blocks = count
    set_pending_directive(
        state,
        CONTINUATION_NUDGE,
        source='Orchestrator._protocol_mode_fallback_message',
    )
    status = MessageAction(
        content=message_text,
        thought=reasoning,
        wait_for_response=False,
    )
    status.protocol_status = True
    status.source = EventSource.AGENT
    return status


def _build_fallback_action(orch: Orchestrator, result) -> Action:
    """Create a message action when non-agent modes return no tool calls.

    The normal parser maps non-tool prose to a user-facing message. This
    fallback preserves that contract for Chat/Plan-style modes when parsing
    produced no durable action.

    Empty text → raises :class:`LLMNoActionError` so the recovery machinery
    in :class:`ActionExecutionService` can issue corrective feedback and retry.
    Agent/Plan text-only output is allowed until a task tracker exists.
    Once a tracker exists, prose is converted into a status card, an
    implicit finish, or a neutral retry prompt depending on tracker state.
    """
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
        raise LLMNoActionError(
            'LLM returned no tool calls and no content. '
            'You must emit at least one tool call per step. '
            'Review the most recent observation in your context — if a command '
            'was detached to the background or truncated, you must follow the '
            'instructions provided in that observation to continue.'
        )
    message_text = _visible_fallback_message_text(message_text)
    if not message_text.strip():
        raise LLMNoActionError(
            'LLM returned only internal tool-call transport markers and no '
            'valid tool action. Re-emit the intended operation as a real tool call.'
        )

    # Extract reasoning content from response if available
    reasoning = ''
    if message is not None:
        reasoning = getattr(message, 'reasoning_content', '') or ''

    executor = getattr(orch, 'executor', None)
    config = getattr(orch, 'config', None)
    active_mode = normalize_interaction_mode(
        getattr(executor, '_active_run_mode', None),
        default=normalize_interaction_mode(getattr(config, 'mode', 'agent')),
    )
    if is_protocol_mode(active_mode):
        state = getattr(executor, '_state', None)
        return _protocol_mode_fallback_message(
            orch,
            message_text,
            reasoning,
            state,
            mode=active_mode,
        )

    logger.warning(
        'LLM returned text-only response with no tool calls in %s mode; '
        'yielding to user.',
        active_mode,
    )
    fallback = MessageAction(
        content=message_text, thought=reasoning, wait_for_response=True
    )
    fallback.source = EventSource.AGENT
    return fallback
