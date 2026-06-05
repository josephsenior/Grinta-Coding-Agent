"""Step recovery / error-handling helpers extracted from :class:`Orchestrator`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.constants import DEFAULT_AGENT_RECOVERABLE_TOOL_ERROR_THRESHOLD
from backend.core.logger import app_logger as logger
from backend.engine._orchestrator_actions import _clear_queued_actions
from backend.engine._orchestrator_helpers import _normalize_recoverable_error_signature
from backend.ledger.action import AgentThinkAction

if TYPE_CHECKING:
    from backend.engine.orchestrator import Orchestrator
    from backend.ledger.action import Action


def _reset_step_recovery_counters(orch: Orchestrator) -> None:
    """Clear context-limit and recoverable tool-call replay counters."""
    orch._consecutive_context_errors = 0
    orch._recoverable_tool_error_signature = ''
    orch._recoverable_tool_error_count = 0
    # The plain-text gate is a *positive* signal of LLM progress: when the
    # LLM emits a real tool call (or the loop is otherwise reset) the
    # consecutive streak is no longer meaningful, so clear it.
    executor = getattr(orch, 'executor', None)
    if executor is not None and hasattr(executor, '_consecutive_plain_text_blocks'):
        executor._consecutive_plain_text_blocks = 0


def _astep_handle_tool_execution_error(
    orch: Orchestrator, e: Exception
) -> Action:
    orch._consecutive_context_errors = 0
    logger.warning('Auto-Healing: Tool Execution Error: %s', e)

    removed = _clear_queued_actions(
        orch, reason='Tool execution failed, aborting batched sequence'
    )
    if removed > 0:
        logger.info(
            'Batched sequence aborted! Dispelled %d blind follow-up actions.',
            removed,
        )

    return AgentThinkAction(
        thought=f'I encountered a tool error: {str(e)}. I will analyze the last tool call and retry.',
    )


def _astep_handle_recoverable_tool_call_shape_error(
    orch: Orchestrator, e: Exception
) -> Action:
    orch._consecutive_context_errors = 0
    logger.warning('Recoverable LLM tool-call error: %s', e)

    error_signature = _normalize_recoverable_error_signature(e)
    if error_signature == orch._recoverable_tool_error_signature:
        orch._recoverable_tool_error_count += 1
    else:
        orch._recoverable_tool_error_signature = error_signature
        orch._recoverable_tool_error_count = 1

    removed = _clear_queued_actions(
        orch, reason='Invalid LLM tool call, aborting batched sequence'
    )
    if removed > 0:
        logger.info(
            'Batched sequence aborted! Dispelled %d blind follow-up actions.',
            removed,
        )

    if (
        orch._recoverable_tool_error_count
        >= DEFAULT_AGENT_RECOVERABLE_TOOL_ERROR_THRESHOLD
    ):
        return AgentThinkAction(
            thought=(
                'The same invalid tool call pattern '
                'repeated 3 times and was blocked. You must change strategy now: '
                're-read relevant file context and emit a different corrected action '
                '(or switch tool), not a near-identical retry.'
            ),
            kind=AgentThinkAction.KIND_RECOVERABLE_ERROR_ESCALATED,
        )

    return AgentThinkAction(
        thought=(
            f'{str(e)}\n'
            'Please emit a corrected tool call with valid JSON arguments.'
        ),
        kind=AgentThinkAction.KIND_RECOVERABLE_ERROR,
    )
