"""Recover the agent loop after step-level failures (LLM, runtime)."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from backend.core.errors import (
    AgentRuntimeDisconnectedError,
    LLMContextWindowExceedError,
    LLMNoActionError,
    LLMNoResponseError,
)
from backend.core.logging.logger import app_logger as logger
from backend.core.schemas import AgentState
from backend.inference.exceptions import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
    RateLimitKind,
    ServiceUnavailableError,
    Timeout,
)
from backend.ledger import EventSource
from backend.ledger.observation import ErrorObservation
from backend.ledger.observation.error import (
    ERROR_CATEGORY_AUTH,
    ERROR_CATEGORY_BAD_REQUEST,
    ERROR_CATEGORY_CONTENT_POLICY,
    ERROR_CATEGORY_CONTEXT_WINDOW,
    ERROR_CATEGORY_DAILY_QUOTA,
    ERROR_CATEGORY_MODEL_NOT_FOUND,
    ERROR_CATEGORY_NETWORK,
    ERROR_CATEGORY_RATE_LIMIT,
    ERROR_CATEGORY_RUNTIME_DISCONNECTED,
    ERROR_CATEGORY_TIMEOUT,
)

if TYPE_CHECKING:
    from backend.orchestration.services.orchestration_context import (
        OrchestrationContext,
    )


# Errors that require the user to intervene before the agent can continue.
# These are genuinely unrecoverable without a config/credential/runtime change,
# so auto-retrying would just loop on the same failure. The agent never sees
# these (they are surfaced to the user, not the model).
#
# NOTE: Transient provider/network failures (Timeout, APIConnectionError,
# InternalServerError, LLMNoResponseError) are intentionally NOT here. The
# LLM's inner Tenacity retry only covers errors raised *before* the first
# streamed chunk — a mid-stream disconnect, a per-chunk stall, or a flaky
# proxy drop bypasses it entirely. Treating those as hard stops made the
# agent halt mid-session on a single transient blip. They now route through
# the retry queue (``_TRANSIENT_LLM_INFRA_EXCEPTIONS`` below) so the session
# backs off and resumes automatically.
_HARD_STOP_EXCEPTIONS = (
    AuthenticationError,
    BadRequestError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    LLMContextWindowExceedError,
    NotFoundError,
    # Persistent runtime disconnects require a full session restart/re-init
    # and should not be treated as survivable tool errors.
    AgentRuntimeDisconnectedError,
)

# Generic Python exceptions previously classified as hard stops.
# These are NOT hard stops: a single incidental AttributeError/KeyError in a
# rarely-hit branch must not halt an otherwise-healthy multi-hour session.
# They are routed through _continue_after_survivable_error so the circuit
# breaker (5 consecutive) and the survivable-error backstop (10 consecutive)
# bound any genuine deterministic loop without requiring user intervention for
# a one-off hiccup.
_SURVIVABLE_PYTHON_EXCEPTIONS = (
    IndexError,
    KeyError,
    TypeError,
    AttributeError,
)

# Errors that need a rate-limit back-off before retrying. These also use the
# retry-queue path so the delay is honoured.
_RATE_LIMITED_EXCEPTIONS = (
    RateLimitError,
    ServiceUnavailableError,
)

# Transport/provider issues that are not actionable by the model but ARE
# worth retrying automatically: the inner LLM Tenacity loop only retries
# errors raised before the first streamed chunk, so mid-stream/transport
# failures and step-level timeouts reach here un-retried. The retry queue
# applies exponential backoff and resumes the run, bounded by
# ``RetryQueue.max_retries`` (falls back to AWAITING_USER_INPUT when the
# queue is unavailable or retries are exhausted).
_TRANSIENT_LLM_INFRA_EXCEPTIONS = (
    APIConnectionError,
    InternalServerError,
    LLMNoResponseError,
    Timeout,
)

# Transient failures that should use the retry queue (exponential backoff +
# automatic RUNNING resume) instead of dropping straight back to the user.
# Rate limits additionally honour any provider-supplied ``Retry-After``.
_QUEUED_RETRY_EXCEPTIONS = _RATE_LIMITED_EXCEPTIONS + _TRANSIENT_LLM_INFRA_EXCEPTIONS


def _is_limit_exceeded_error(exc: Exception) -> bool:
    """Return True if this exception signals an agent budget or iteration hard limit.

    These are terminal conditions the agent cannot self-recover from; they
    must be treated as hard stops that return control to the user rather than
    re-triggering the step loop.

    Detection uses ``isinstance(AgentLimitExceededError)`` so the recovery
    path is robust against upstream error-message format changes.
    """
    from backend.core.errors import AgentLimitExceededError

    return isinstance(exc, AgentLimitExceededError)


def _recovery_may_set_state(controller, new_state: AgentState) -> bool:
    """True only when the formal state graph allows ``current → new_state``.

    Late exceptions (e.g. provider 429) can arrive after the user interrupted
    and the controller is already ``STOPPED``; forcing ``RATE_LIMITED`` then
    raises :class:`InvalidStateTransitionError`.
    """
    from backend.orchestration.services.state_transition_service import (
        VALID_TRANSITIONS,
    )

    try:
        current = controller.get_agent_state()
    except Exception:
        logger.debug('get_agent_state failed during recovery guard', exc_info=True)
        return False
    allowed = VALID_TRANSITIONS.get(current)
    return allowed is not None and new_state in allowed


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

    def _record_circuit_breaker_error(self, controller, exc: Exception) -> None:
        from backend.orchestration.services.error_formatting import (
            exception_is_notify_ui_only,
        )

        # API/provider/runtime failures are HUD-only and retried automatically.
        # They must not advance the consecutive-error counter or false-trip the
        # circuit breaker into CIRCUIT_BREAKER_WARNING spam.
        if exception_is_notify_ui_only(
            exc,
            _HARD_STOP_EXCEPTIONS,
            _RATE_LIMITED_EXCEPTIONS,
            _TRANSIENT_LLM_INFRA_EXCEPTIONS,
        ):
            return

        try:
            controller.circuit_breaker_service.record_error(exc)
        except Exception:
            logger.debug('circuit_breaker record_error failed', exc_info=True)

    def _clear_pending_action_context(self, controller) -> None:
        pending_svc = _resolve_pending_action_service(controller)
        if pending_svc is None:
            return
        pending = pending_svc.get()
        if pending is None:
            return
        self._context.discard_invocation_context_for_action(pending)
        pending_svc.pop_for_cause(getattr(pending, 'id', None))

    def _emit_exception_observation(self, exc: Exception) -> None:
        msg, err_id, notify_ui_only = self._format_exception(exc)
        error_category = self._error_category_for(exc)

        # Always emit an ErrorObservation so the failure is visible *somewhere*.
        # ``notify_ui_only`` (set by ``_format_exception``) decides whether the
        # model also sees it: transient infra errors, rate limits, timeouts and
        # auth failures are HUD-only (the orchestrator/retry-queue handles them,
        # so the model must not be told a hard failure occurred and re-plan
        # around it); genuinely model-actionable errors are surfaced to the LLM
        # transcript so it can adapt on the next turn.
        self._context.emit_event(
            ErrorObservation(
                content=msg,
                error_id=err_id,
                notify_ui_only=notify_ui_only,
                error_category=error_category,
            ),
            EventSource.ENVIRONMENT,
        )

    @staticmethod
    def _error_category_for(exc: Exception) -> str | None:
        """Return a structured error category constant from the actual exception type.

        This is the single authoritative place that maps exception → category.
        The UI reads ``ErrorObservation.error_category`` directly so it never
        needs to parse rendered error text.
        """
        from backend.core.errors import (
            AgentRuntimeDisconnectedError,
            LLMContextWindowExceedError,
        )
        from backend.inference.exceptions import (
            APIConnectionError,
            AuthenticationError,
            BadRequestError,
            ContentPolicyViolationError,
            ContextWindowExceededError,
            InternalServerError,
            NotFoundError,
            RateLimitError,
            ServiceUnavailableError,
            Timeout,
        )

        if isinstance(exc, (RateLimitError, ServiceUnavailableError)):
            if isinstance(exc, RateLimitError) and exc.kind == RateLimitKind.RPD:
                return ERROR_CATEGORY_DAILY_QUOTA
            return ERROR_CATEGORY_RATE_LIMIT
        if isinstance(exc, AuthenticationError):
            return ERROR_CATEGORY_AUTH
        if isinstance(exc, BadRequestError):
            return ERROR_CATEGORY_BAD_REQUEST
        if isinstance(exc, (ContextWindowExceededError, LLMContextWindowExceedError)):
            return ERROR_CATEGORY_CONTEXT_WINDOW
        if isinstance(exc, Timeout):
            return ERROR_CATEGORY_TIMEOUT
        if isinstance(exc, (APIConnectionError, InternalServerError)):
            return ERROR_CATEGORY_NETWORK
        if isinstance(exc, NotFoundError):
            return ERROR_CATEGORY_MODEL_NOT_FOUND
        if isinstance(exc, AgentRuntimeDisconnectedError):
            return ERROR_CATEGORY_RUNTIME_DISCONNECTED
        if isinstance(exc, ContentPolicyViolationError):
            return ERROR_CATEGORY_CONTENT_POLICY
        return None

    async def _set_awaiting_user_input_if_allowed(self, controller) -> None:
        if _recovery_may_set_state(controller, AgentState.AWAITING_USER_INPUT):
            retry_service = getattr(controller, 'retry_service', None)
            if retry_service and hasattr(retry_service, 'reset_retry_metrics'):
                retry_service.reset_retry_metrics()
            await self._context.set_agent_state(AgentState.AWAITING_USER_INPUT)

    async def _handle_hard_stop_exception(self, controller, exc: Exception) -> bool:
        if not isinstance(exc, _HARD_STOP_EXCEPTIONS):
            return False
        # For context window errors, attempt aggressive compaction before giving up.
        if isinstance(exc, (ContextWindowExceededError, LLMContextWindowExceedError)):
            if await self._attempt_aggressive_compaction(controller):
                return True
        await self._set_awaiting_user_input_if_allowed(controller)
        return True

    async def _attempt_aggressive_compaction(self, controller) -> bool:
        """Try to aggressively compact context and retry. Returns True if recovery succeeded."""
        try:
            agent = getattr(controller, 'agent', None)
            agent_config = getattr(agent, 'config', None) if agent else None
            if not getattr(agent_config, 'enable_history_truncation', False):
                return False

            event_stream = getattr(controller, 'event_stream', None)
            if event_stream is None:
                return False

            from backend.ledger.action.agent import CondensationRequestAction
            from backend.ledger.observation.status import StatusObservation

            self._context.emit_event(
                StatusObservation(
                    content='Context window exceeded. Compacting context before retrying...',
                    status_type='compaction',
                ),
                EventSource.ENVIRONMENT,
            )
            self._context.emit_event(
                CondensationRequestAction(),
                EventSource.AGENT,
            )
            logger.info('Queued aggressive compaction after context-window overflow')
            if controller.get_agent_state() == AgentState.RUNNING:
                schedule_step_soon = getattr(controller, 'schedule_step_soon', None)
                if callable(schedule_step_soon):
                    schedule_step_soon()
                else:
                    controller.step()
            return True
        except Exception:
            logger.warning('Aggressive compaction failed', exc_info=True)
        return False

    async def _handle_limit_exceeded_exception(
        self, controller, exc: Exception
    ) -> bool:
        if not _is_limit_exceeded_error(exc):
            return False
        logger.warning(
            'Agent limit exceeded (%s): stopping agent loop and returning to user',
            exc,
        )
        await self._set_awaiting_user_input_if_allowed(controller)
        return True

    def _emit_rate_limit_think_observation(self, controller, exc: Exception) -> None:
        """Record a rate-limit event WITHOUT polluting the agent's context.

        The agent has no rate-limit mitigation tools — the system handles
        recovery automatically via the inner Tenacity loop and the outer
        retry queue (see ``backend/core/retry_queue.py``). Emitting an
        ``AgentThinkObservation`` here costs ~50–100 tokens per event for
        information the agent cannot act on, and risks making the agent
        believe a hard failure has already occurred.

        Policy (per design discussion 2026-05):
          * Silent on transient rate-limits (this method is now a no-op for
            the LLM context).
          * The CLI HUD still shows ``[TPM · ETA Xs]`` because the retry
            service emits a separate ``StatusObservation`` that is UI-only.
          * The compact ``ErrorObservation`` for 429/503 uses
            ``notify_ui_only=True`` so it never appears in LLM message assembly
            (orchestrator handles retries; the model should see the next
            successful tool result only).

        We keep a structured DEBUG log so operators can still trace events.
        """
        kind = getattr(exc, 'kind', None)
        retry_after = getattr(exc, 'retry_after', None)
        logger.debug(
            'rate_limit_event suppressed_from_agent_context kind=%s retry_after=%s exc=%s',
            getattr(kind, 'value', kind),
            retry_after,
            type(exc).__name__,
        )
        # Reference ``controller`` to keep the signature stable for callers
        # that pass it positionally.
        _ = controller

    def _record_rate_limit_to_governor(self, controller, exc: Exception) -> None:
        """Teach the rate governor about an observed 429 (TPM only, best-effort)."""
        governor = getattr(controller, 'rate_governor', None)
        if governor is None or not hasattr(governor, 'record_rate_limit_event'):
            return
        try:
            governor.record_rate_limit_event(
                provider=getattr(exc, 'llm_provider', None),
                model=getattr(exc, 'model', None),
                kind=getattr(exc, 'kind', None),
            )
        except Exception:
            logger.debug('record_rate_limit_event failed', exc_info=True)

    async def _schedule_queued_retry(self, controller, exc: Exception) -> bool:
        try:
            if isinstance(exc, _RATE_LIMITED_EXCEPTIONS):
                self._emit_rate_limit_think_observation(controller, exc)
                self._record_rate_limit_to_governor(controller, exc)
            return await controller.retry_service.schedule_retry_after_failure(exc)
        except Exception:
            logger.debug('schedule_retry_after_failure failed', exc_info=True)
            return False

    async def _handle_queued_retry_exception(self, controller, exc: Exception) -> bool:
        if not isinstance(exc, _QUEUED_RETRY_EXCEPTIONS):
            return False

        if isinstance(exc, RateLimitError):
            if exc.kind == RateLimitKind.RPD:
                logger.warning('Daily quota exhausted.')
                await self._set_awaiting_user_input_if_allowed(controller)
                return True

            retry_after = getattr(exc, 'retry_after', None)
            if retry_after is not None:
                from backend.orchestration.services.retry_queue import get_retry_queue

                queue = get_retry_queue()
                max_delay = getattr(queue, 'max_delay', 30.0) if queue else 30.0
                if retry_after > max_delay:
                    logger.warning(
                        'Rate limit retry_after (%.1fs) exceeds max delay (%.1fs). Aborting queued retry.',
                        retry_after,
                        max_delay,
                    )
                    await self._set_awaiting_user_input_if_allowed(controller)
                    return True

        if not _recovery_may_set_state(controller, AgentState.RATE_LIMITED):
            logger.info(
                'Skipping queued-retry recovery transition (state=%s); '
                'error was still recorded.',
                controller.get_agent_state(),
            )
            return True

        scheduled = await self._schedule_queued_retry(controller, exc)
        if scheduled:
            await self._context.set_agent_state(AgentState.RATE_LIMITED)
            return True

        logger.warning(
            'Queued retry unavailable for %s; returning to AWAITING_USER_INPUT',
            type(exc).__name__,
        )
        await self._set_awaiting_user_input_if_allowed(controller)
        return True

    async def _continue_after_survivable_error(
        self, controller, exc: Exception
    ) -> None:
        logger.warning(
            'Agent-survivable error (%s): staying RUNNING so model can adapt',
            type(exc).__name__,
        )
        # Secondary safety net: track consecutive survivable-error self-steps
        # to prevent infinite retry loops when the circuit breaker is disabled
        # or misconfigured.  The circuit breaker is the primary defence
        # (default: 5 consecutive errors); this is a hard backstop.
        state = getattr(controller, 'state', None)
        if state is not None and hasattr(state, 'extra_data'):
            count = state.extra_data.get('__survivable_error_consecutive', 0) + 1
            state.extra_data['__survivable_error_consecutive'] = count
            _MAX_SURVIVABLE = 10
            if count > _MAX_SURVIVABLE:
                logger.error(
                    'Survivable error loop detected: %d consecutive errors. '
                    'Transitioning to AWAITING_USER_INPUT.',
                    count,
                )
                state.extra_data['__survivable_error_consecutive'] = 0
                await self._set_awaiting_user_input_if_allowed(controller)
                return
        else:
            count = 0

        self._inject_task_reconciliation_directive(controller, exc)
        pause = 2.0 if isinstance(exc, (InternalServerError, Timeout)) else 1.0
        await asyncio.sleep(pause)
        # Verify that no other recovery path or user action changed the state.
        if controller.get_agent_state() != AgentState.RUNNING:
            logger.debug(
                'Skipping post-error step: state changed during sleep (now %s)',
                controller.get_agent_state(),
            )
            return
        if controller.get_agent_state() == AgentState.RUNNING:
            schedule_step_soon = getattr(controller, 'schedule_step_soon', None)
            if callable(schedule_step_soon):
                schedule_step_soon()
            else:
                controller.step()

    async def _route_exception_recovery(self, controller, exc: Exception) -> bool:
        if await self._handle_hard_stop_exception(controller, exc):
            return True
        if await self._handle_limit_exceeded_exception(controller, exc):
            return True
        return await self._handle_queued_retry_exception(controller, exc)

    @staticmethod
    def _state_has_planning_directive(state) -> bool:
        turn_signals = getattr(state, 'turn_signals', None)
        return bool(
            getattr(turn_signals, 'planning_directive', None) if turn_signals else None
        )

    @staticmethod
    def _recent_history_slice(state) -> list:
        history = getattr(state, 'history', []) or []
        return history[-3:] if isinstance(history, list) else []

    @staticmethod
    def _event_is_mcp_validation_failure(event) -> bool:
        observation_type = str(getattr(event, 'observation', '')).lower()
        content = getattr(event, 'content', '')
        if observation_type != 'mcp' or not isinstance(content, str):
            return False

        try:
            payload = json.loads(content)
        except Exception:
            return False
        if not isinstance(payload, dict):
            return False

        error_code = str(payload.get('error_code') or '')
        error_text = str(payload.get('error') or '')
        return error_code == 'MCP_TOOL_VALIDATION_ERROR' or '-32602' in error_text

    @staticmethod
    def _inject_timeout_planning_directive(state) -> None:
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

    async def react_to_exception(self, exc: Exception) -> None:
        controller = self._context.get_controller()

        self._apply_timeout_planning_routing(controller, exc)

        self._record_circuit_breaker_error(controller, exc)
        self._clear_pending_action_context(controller)
        self._emit_exception_observation(exc)

        # ------------------------------------------------------------------ #
        # State transition after an error.
        #
        # Hard-stop errors (auth failure, context window, model not found):
        #   → AWAITING_USER_INPUT — user must fix config/credentials first.
        #
        # Budget / iteration hard limits:
        #   → AWAITING_USER_INPUT — agent cannot self-recover; re-stepping
        #     would immediately raise the same error again in an infinite loop.
        #
        # Rate-limited errors (429, 503) and provider/network timeouts:
        #   → AWAITING_USER_INPUT + retry queue — the queue handles the
        #     back-off delay and transitions back to RUNNING automatically.
        #     For 429/503/Timeout and transient LLM infra (connection, 5xx,
        #     empty response) the ``ErrorObservation`` is ``notify_ui_only``
        #     (HUD), not embedded in the LLM transcript.
        #
        # All other errors (unexpected runtime exceptions, tool failures):
        #   → Stay RUNNING — the error observation is already in the model's
        #     context; it can read it and adapt its next action.  The circuit
        #     breaker (default: 5 consecutive errors) acts as the safety net
        #     against infinite failure loops.
        #
        # BadRequestError (invalid temperature, unsupported params, etc.) is a
        # hard stop with ``notify_ui_only`` — user/config must change first.
        # Malformed tool-call JSON is handled earlier in ActionExecutionService.
        # ------------------------------------------------------------------ #
        if await self._route_exception_recovery(controller, exc):
            return

        await self._continue_after_survivable_error(controller, exc)

    @staticmethod
    def _event_is_background_detach_warning(event) -> bool:
        content = getattr(event, 'content', '')
        if not isinstance(content, str):
            return False
        return '[BACKGROUND_DETACH]' in content

    @staticmethod
    def _inject_background_detach_planning_directive(state) -> None:
        directive = (
            'Your previous command was detached to the background because it '
            'exceeded the idle-output timeout. It is STILL RUNNING. '
            'Before taking any other action or writing new commands, you MUST '
            'call `terminal_read` with the session ID provided in the previous '
            'observation to check its progress.'
        )
        state.set_planning_directive(
            directive,
            source='RecoveryService.background_detach_recovery',
        )
        logger.warning(
            'Injected planning directive after LLMNoActionError due to recent background detach'
        )

    def _apply_timeout_planning_routing(self, controller, exc: Exception) -> None:
        """Route timeout recoveries based on recent MCP validation failures or background detaches."""
        state = getattr(controller, 'state', None)
        if state is None or not hasattr(state, 'set_planning_directive'):
            return

        if self._state_has_planning_directive(state):
            return

        recent = self._recent_history_slice(state)

        # 1. MCP Validation Timeout Recovery
        if isinstance(exc, Timeout) and any(
            self._event_is_mcp_validation_failure(event) for event in reversed(recent)
        ):
            self._inject_timeout_planning_directive(state)
            return

        # 2. Background Detach + Empty Response Recovery
        if isinstance(exc, LLMNoActionError) and any(
            self._event_is_background_detach_warning(event)
            for event in reversed(recent)
        ):
            self._inject_background_detach_planning_directive(state)
            return

    def _inject_task_reconciliation_directive(self, controller, exc: Exception) -> None:
        """Inject a directive requiring task_tracker reconciliation when ``in_progress`` steps exist.

        After a survivable error the model continues, but if a plan step is
        still marked ``in_progress`` the model tends to ignore it.  This directive
        forces the next turn to explicitly reconcile the plan via
        ``task_tracker update`` before doing any other work.
        """
        from backend.core.tasks.task_status import TASK_STATUS_IN_PROGRESS

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

        in_progress_steps = [
            s
            for s in getattr(plan, 'steps', [])
            if getattr(s, 'status', '') == TASK_STATUS_IN_PROGRESS
        ]
        if not in_progress_steps:
            return

        ids = ', '.join(getattr(s, 'id', '?') for s in in_progress_steps)
        directive = f'Recoverable error during in_progress plan step(s): [{ids}].'
        state.set_planning_directive(
            directive,
            source=f'RecoveryService.task_reconciliation({type(exc).__name__})',
        )
        logger.info(
            'Injected task-reconciliation directive for in_progress steps: %s',
            ids,
        )

    @staticmethod
    def _format_exception(exc: Exception) -> tuple[str, str, bool]:
        from backend.orchestration.services.error_formatting import format_exception

        return format_exception(
            exc,
            _HARD_STOP_EXCEPTIONS,
            _RATE_LIMITED_EXCEPTIONS,
            _TRANSIENT_LLM_INFRA_EXCEPTIONS,
        )


def _resolve_error_id(exc: Exception) -> str:
    from backend.orchestration.services.error_formatting import resolve_error_id

    return resolve_error_id(exc)


def _format_error_text(exc: Exception) -> str:
    from backend.orchestration.services.error_formatting import format_error_text

    return format_error_text(exc)


def _format_error_guidance(exc: Exception) -> str:
    from backend.orchestration.services.error_formatting import format_error_guidance

    return format_error_guidance(exc)


def _format_rate_limit_text(exc: Exception, rate_kind, retry_after) -> str:
    from backend.orchestration.services.error_formatting import (
        _format_rate_limit_text as _impl,
    )

    return _impl(exc, rate_kind, retry_after)


def _format_rate_limit_guidance(rate_kind, retry_after) -> str:
    from backend.orchestration.services.error_formatting import (
        _format_rate_limit_guidance as _impl,
    )

    return _impl(rate_kind, retry_after)
