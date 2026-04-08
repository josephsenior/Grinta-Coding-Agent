"""Recover the agent loop after step-level failures (LLM, runtime)."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from backend.core.errors import AgentRuntimeError, LLMContextWindowExceedError
from backend.core.logger import app_logger as logger
from backend.core.schemas import AgentState
from backend.inference.exceptions import (
    AuthenticationError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)
from backend.ledger import EventSource
from backend.ledger.observation import ErrorObservation

if TYPE_CHECKING:
    from backend.orchestration.services.orchestration_context import (
        OrchestrationContext,
    )


# Errors that require the user to intervene before the agent can continue.
# Everything else is considered "agent-survivable": the error is injected as
# an observation and the agent re-steps so the model can adapt its approach.
_HARD_STOP_EXCEPTIONS = (
    AuthenticationError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    LLMContextWindowExceedError,
    NotFoundError,
)

# Errors that need a rate-limit back-off before retrying. These also use the
# retry-queue path so the delay is honoured.
_RATE_LIMITED_EXCEPTIONS = (
    RateLimitError,
    ServiceUnavailableError,
)


def _resolve_pending_action_service(controller):
    controller_dict = getattr(controller, '__dict__', {})
    services = controller_dict.get('services')
    if services is not None:
        service = getattr(services, 'pending_action', None)
        if service is not None:
            return service
    service = controller_dict.get('pending_action_service')
    if service is not None:
        return service
    return getattr(controller, 'pending_action_service', None)


class RecoveryService:
    """Emits recoverable ErrorObservation, optional retry scheduling, and advances the loop."""

    def __init__(self, context: OrchestrationContext) -> None:
        self._context = context

    async def react_to_exception(self, exc: Exception) -> None:
        controller = self._context.get_controller()

        self._apply_timeout_planning_routing(controller, exc)

        try:
            controller.circuit_breaker_service.record_error(exc)
        except Exception:
            logger.debug('circuit_breaker record_error failed', exc_info=True)

        pending_svc = _resolve_pending_action_service(controller)
        if pending_svc is not None:
            pending = pending_svc.get()
            if pending is not None:
                self._context.discard_invocation_context_for_action(pending)
                pending_svc.set(None)

        msg, err_id, notify_ui_only = self._format_exception(exc)
        self._context.emit_event(
            ErrorObservation(
                content=msg,
                error_id=err_id,
                notify_ui_only=notify_ui_only,
            ),
            EventSource.ENVIRONMENT,
        )

        # ------------------------------------------------------------------ #
        # State transition after an error.
        #
        # Hard-stop errors (auth failure, context window, model not found):
        #   → AWAITING_USER_INPUT — user must fix config/credentials first.
        #
        # Rate-limited errors (429, 503):
        #   → AWAITING_USER_INPUT + retry queue — the queue handles the
        #     back-off delay and transitions back to RUNNING automatically.
        #
        # All other errors (transient 5xx, bad-request from wrong tool args,
        #   timeout, unexpected runtime exceptions):
        #   → Stay RUNNING — the error observation is already in the model's
        #     context; it can read it and adapt its next action.  The circuit
        #     breaker (default: 5 consecutive errors) acts as the safety net
        #     against infinite failure loops.
        # ------------------------------------------------------------------ #
        if isinstance(exc, _HARD_STOP_EXCEPTIONS):
            await self._context.set_agent_state(AgentState.AWAITING_USER_INPUT)
            return

        if isinstance(exc, _RATE_LIMITED_EXCEPTIONS):
            try:
                await controller.retry_service.schedule_retry_after_failure(exc)
            except Exception:
                logger.debug('schedule_retry_after_failure failed', exc_info=True)
            await self._context.set_agent_state(AgentState.AWAITING_USER_INPUT)
            return

        # Agent-survivable error: brief pause so we don't hammer the provider,
        # then continue. The model sees the ErrorObservation and can try a
        # different approach.
        logger.warning(
            'Agent-survivable error (%s): staying RUNNING so model can adapt',
            type(exc).__name__,
        )
        self._inject_task_reconciliation_directive(controller, exc)
        pause = 1.0
        if isinstance(exc, (InternalServerError, Timeout)):
            pause = 2.0
        await asyncio.sleep(pause)
        if controller.get_agent_state() == AgentState.RUNNING:
            controller.step()

    def _apply_timeout_planning_routing(self, controller, exc: Exception) -> None:
        """Route timeout recoveries based on recent MCP validation failures."""
        if not isinstance(exc, Timeout):
            return

        state = getattr(controller, 'state', None)
        if state is None or not hasattr(state, 'set_planning_directive'):
            return

        # Avoid clobbering any directive that is already queued for this turn.
        turn_signals = getattr(state, 'turn_signals', None)
        existing = (
            getattr(turn_signals, 'planning_directive', None) if turn_signals else None
        )
        if existing:
            return

        history = getattr(state, 'history', []) or []
        recent = history[-3:] if isinstance(history, list) else []

        for event in reversed(recent):
            observation_type = str(getattr(event, 'observation', '')).lower()
            content = getattr(event, 'content', '')
            if not isinstance(content, str):
                continue
            if observation_type != 'mcp':
                continue

            payload = None
            try:
                payload = json.loads(content)
            except Exception:
                payload = None

            if isinstance(payload, dict):
                error_code = str(payload.get('error_code') or '')
                error_text = str(payload.get('error') or '')
                if error_code == 'MCP_TOOL_VALIDATION_ERROR' or '-32602' in error_text:
                    directive = (
                        'Recent MCP call failed due to tool argument validation. '
                        'Before any broad reasoning, select exactly one MCP tool, '
                        'rebuild arguments to match its schema types, and retry once. '
                        'If still invalid, explain the exact required argument shape to the user.'
                    )
                    state.set_planning_directive(
                        directive,
                        source='RecoveryService.mcp_validation_timeout',
                    )
                    logger.warning(
                        'Injected planning directive after Timeout due to recent MCP validation error'
                    )
                    return

    def _inject_task_reconciliation_directive(self, controller, exc: Exception) -> None:
        """Inject a directive requiring task_tracker reconciliation when ``doing`` steps exist.

        After a survivable error the model continues, but if a plan step is
        still marked ``doing`` the model tends to ignore it.  This directive
        forces the next turn to explicitly reconcile the plan via
        ``task_tracker update`` before doing any other work.
        """
        from backend.core.task_status import TASK_STATUS_DOING

        state = getattr(controller, 'state', None)
        if state is None or not hasattr(state, 'set_planning_directive'):
            return

        # Don't clobber an existing directive (e.g. MCP-validation one).
        turn_signals = getattr(state, 'turn_signals', None)
        existing = (
            getattr(turn_signals, 'planning_directive', None) if turn_signals else None
        )
        if existing:
            return

        plan = getattr(state, 'plan', None)
        if plan is None:
            return

        doing_steps = [
            s for s in getattr(plan, 'steps', [])
            if getattr(s, 'status', '') == TASK_STATUS_DOING
        ]
        if not doing_steps:
            return

        ids = ', '.join(getattr(s, 'id', '?') for s in doing_steps)
        directive = (
            f'A recoverable error just occurred while plan step(s) [{ids}] '
            f'had status "doing". Before any other work, call task_tracker '
            f'update to reconcile the plan: move failed steps back to "todo" '
            f'(with a result note), or keep them "doing" if you intend to '
            f'retry immediately. Do NOT leave stale "doing" steps unaddressed.'
        )
        state.set_planning_directive(
            directive,
            source=f'RecoveryService.task_reconciliation({type(exc).__name__})',
        )
        logger.info(
            'Injected task-reconciliation directive for doing steps: %s', ids,
        )

    @staticmethod
    def _format_exception(exc: Exception) -> tuple[str, str, bool]:
        notify_ui_only = isinstance(
            exc,
            (AuthenticationError, ContentPolicyViolationError),
        )
        err_id = 'AGENT_STEP_EXCEPTION'
        if isinstance(exc, Timeout):
            err_id = 'LLM_TIMEOUT'
        elif isinstance(exc, LLMContextWindowExceedError | ContextWindowExceededError):
            err_id = 'LLM_CONTEXT_WINDOW_EXCEEDED'
        elif isinstance(exc, AgentRuntimeError):
            err_id = 'AGENT_RUNTIME_ERROR'

        text = f'{type(exc).__name__}: {exc}'

        # Hard stops need user action; survivable errors get guidance for the model.
        if isinstance(exc, _HARD_STOP_EXCEPTIONS):
            guidance = (
                'This error requires user intervention (check credentials, model name, '
                'or context window). Wait for the user to fix the configuration.'
            )
        elif isinstance(exc, _RATE_LIMITED_EXCEPTIONS):
            guidance = 'Rate limit reached. Waiting before retrying — no action needed.'
        else:
            guidance = (
                'A transient error occurred on this step. The error has been recorded. '
                'Review what went wrong, choose a different approach or tool, and continue.'
            )
        return f'{text}\n\n{guidance}', err_id, notify_ui_only
