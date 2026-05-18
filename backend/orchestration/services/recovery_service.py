"""Recover the agent loop after step-level failures (LLM, runtime)."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from backend.core.errors import (
    AgentRuntimeDisconnectedError,
    AgentRuntimeError,
    LLMContextWindowExceedError,
    LLMNoActionError,
    LLMNoResponseError,
)
from backend.core.logger import app_logger as logger
from backend.core.schemas import AgentState
from backend.inference.exceptions import (
    APIConnectionError,
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
from backend.ledger.observation.agent import AgentThinkObservation
from backend.ledger.observation.error import (
    ERROR_CATEGORY_AUTH,
    ERROR_CATEGORY_CONTENT_POLICY,
    ERROR_CATEGORY_CONTEXT_WINDOW,
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
# Everything else is considered "agent-survivable": the error is injected as
# an observation and the agent re-steps so the model can adapt its approach.
_HARD_STOP_EXCEPTIONS = (
    AuthenticationError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    LLMContextWindowExceedError,
    NotFoundError,
    # Persistent runtime disconnects require a full session restart/re-init
    # and should not be treated as survivable tool errors.
    AgentRuntimeDisconnectedError,
)

# Errors that need a rate-limit back-off before retrying. These also use the
# retry-queue path so the delay is honoured.
_RATE_LIMITED_EXCEPTIONS = (
    RateLimitError,
    ServiceUnavailableError,
)

# Transient provider failures that should use the retry queue instead of
# dropping straight back to the user. Timeouts are included here on purpose:
# they indicate provider/network stall, not a task-level dead end.
_QUEUED_RETRY_EXCEPTIONS = _RATE_LIMITED_EXCEPTIONS + (Timeout,)

# After inner LLM retries (see ``LLM_RETRY_EXCEPTIONS`` in ``llm.py``), these
# are still transport/provider issues—not actionable by the model.
_TRANSIENT_LLM_INFRA_EXCEPTIONS = (
    APIConnectionError,
    InternalServerError,
    LLMNoResponseError,
)


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
        from backend.inference.exceptions import (
            APIConnectionError,
            RateLimitError,
            Timeout,
        )

        if isinstance(exc, (RateLimitError, APIConnectionError, Timeout)):
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
        pending_svc.set(None)

    def _emit_exception_observation(self, exc: Exception) -> None:
        msg, err_id, notify_ui_only = self._format_exception(exc)
        error_category = self._error_category_for(exc)
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
            ContentPolicyViolationError,
            ContextWindowExceededError,
            InternalServerError,
            NotFoundError,
            RateLimitError,
            ServiceUnavailableError,
            Timeout,
        )

        if isinstance(exc, (RateLimitError, ServiceUnavailableError)):
            return ERROR_CATEGORY_RATE_LIMIT
        if isinstance(exc, AuthenticationError):
            return ERROR_CATEGORY_AUTH
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
            services = getattr(controller, 'services', None)
            if services is None:
                return False
            context_service = getattr(services, 'context', None)
            if context_service is None:
                return False
            # Force a compaction by calling the compactor directly.
            compactor = getattr(context_service, 'compactor', None)
            if compactor is None:
                return False
            # Emit a think observation so the agent knows what happened.
            self._context.emit_event(
                AgentThinkObservation(
                    content='Context window exceeded. Aggressively compacting context to continue.',
                ),
                EventSource.ENVIRONMENT,
            )
            # Trigger compaction via the context service.
            force_compaction = getattr(context_service, 'force_compaction', None)
            if callable(force_compaction):
                await force_compaction()
                logger.info('Aggressive compaction succeeded, resuming agent')
                if _recovery_may_set_state(controller, AgentState.RUNNING):
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

        from backend.inference.exceptions import RateLimitError, RateLimitKind

        if isinstance(exc, RateLimitError):
            if getattr(exc, 'kind', None) == RateLimitKind.RPD:
                logger.warning('Daily quota exhausted.')
                await self._set_awaiting_user_input_if_allowed(controller)
                return True

            retry_after = getattr(exc, 'retry_after', None)
            if retry_after is not None:
                from backend.core.retry_queue import get_retry_queue

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
        # Reset the consecutive-error counter on successful recovery.
        # Without this, the counter grows monotonically and eventually
        # triggers the hard backstop (>20) even when the agent recovers
        # between intermittent failures.
        if state is not None and hasattr(state, 'extra_data'):
            state.extra_data['__survivable_error_consecutive'] = 0
        # Atomic check-then-step: verify state is still RUNNING before stepping.
        if not _recovery_may_set_state(controller, AgentState.RUNNING):
            logger.debug(
                'Skipping post-error step: state changed during sleep (now %s)',
                controller.get_agent_state(),
            )
            return
        if controller.get_agent_state() == AgentState.RUNNING:
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
        # All other errors (transient 5xx, bad-request from wrong tool args,
        #   timeout, unexpected runtime exceptions):
        #   → Stay RUNNING — the error observation is already in the model's
        #     context; it can read it and adapt its next action.  The circuit
        #     breaker (default: 5 consecutive errors) acts as the safety net
        #     against infinite failure loops.
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
            s
            for s in getattr(plan, 'steps', [])
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
            'Injected task-reconciliation directive for doing steps: %s',
            ids,
        )

    @staticmethod
    def _format_exception(exc: Exception) -> tuple[str, str, bool]:
        # Rate-limit / 503 / LLM Timeout / connection & 5xx after inner retries:
        # orchestrator recovers without model help. Same mechanism as auth failures:
        # emit for HUD/toast but omit from LLM context (see
        # ContextMemory._process_observation notify_ui_only guard).
        notify_ui_only = (
            isinstance(
                exc,
                (AuthenticationError, ContentPolicyViolationError, Timeout),
            )
            or isinstance(exc, _RATE_LIMITED_EXCEPTIONS)
            or isinstance(exc, _TRANSIENT_LLM_INFRA_EXCEPTIONS)
        )
        err_id = 'AGENT_STEP_EXCEPTION'
        if isinstance(exc, Timeout):
            err_id = 'LLM_TIMEOUT'
        elif isinstance(exc, LLMContextWindowExceedError | ContextWindowExceededError):
            err_id = 'LLM_CONTEXT_WINDOW_EXCEEDED'
        elif isinstance(exc, AgentRuntimeDisconnectedError):
            err_id = 'AGENT_RUNTIME_DISCONNECTED'
        elif isinstance(exc, AgentRuntimeError):
            err_id = 'AGENT_RUNTIME_ERROR'

        if isinstance(exc, AuthenticationError):
            model = getattr(exc, 'model', None) or '?'
            provider = getattr(exc, 'llm_provider', None) or '?'
            text = (
                f'{exc}\n'
                f'The LLM provider ({provider}) rejected access to model "{model}".\n'
                f'Run /settings to update your model or API key.'
            )
        elif isinstance(exc, _RATE_LIMITED_EXCEPTIONS):
            rate_kind = getattr(exc, 'kind', None)
            retry_after = getattr(exc, 'retry_after', None)
            text = _format_rate_limit_text(exc, rate_kind, retry_after)
        else:
            text = f'{type(exc).__name__}: {exc}'

        # Hard stops need user action; survivable errors get guidance for the model.
        if isinstance(exc, AgentRuntimeDisconnectedError):
            guidance = (
                'The agent runtime has disconnected or failed to initialize. '
                'This is a persistent state that requires a session reset or '
                'infrastructure check. CONTROL IS RETURNED TO USER.'
            )
        elif isinstance(exc, AuthenticationError):
            guidance = ''
        elif isinstance(exc, _HARD_STOP_EXCEPTIONS):
            guidance = (
                'This error requires user intervention (check credentials, model name, '
                'or context window). Wait for the user to fix the configuration.'
            )
        elif isinstance(exc, _RATE_LIMITED_EXCEPTIONS):
            rate_kind = getattr(exc, 'kind', None)
            retry_after = getattr(exc, 'retry_after', None)
            guidance = _format_rate_limit_guidance(rate_kind, retry_after)
        elif isinstance(exc, Timeout):
            guidance = (
                'The provider timed out on this step. Automatic backoff and retry '
                'will run if the retry queue is available; otherwise the agent will '
                'return to the prompt.'
            )
        elif isinstance(exc, _TRANSIENT_LLM_INFRA_EXCEPTIONS):
            guidance = (
                'Transient provider or network issue; the runtime retries automatically. '
                'No change to your approach is required unless this keeps failing.'
            )
        else:
            guidance = (
                'A transient error occurred on this step. The error has been recorded. '
                'Review what went wrong, choose a different approach or tool, and continue.'
            )
        if guidance:
            text = f'{text}\n\n{guidance}'
        return text, err_id, notify_ui_only


def _format_rate_limit_text(exc: Exception, rate_kind, retry_after) -> str:
    """Format rate limit error text with specific kind info."""
    import re

    from backend.inference.exceptions import RateLimitKind

    kind_value = getattr(rate_kind, 'value', str(rate_kind)) if rate_kind else None
    base_text = str(exc) if exc.args else 'Rate limit exceeded'
    base_text = re.sub(r'https?://\S+', '[link]', base_text)

    if kind_value == RateLimitKind.RPD.value:
        return (
            '⚠️ Daily quota exhausted. Your free-tier limit has been reached for today.'
        )
    elif kind_value == RateLimitKind.RPM.value:
        return '⚠️ Too many requests per minute (RPM limit).'
    elif kind_value == RateLimitKind.TPM.value:
        return '⚠️ Too many tokens used per minute (TPM limit).'
    else:
        return f'⚠️ Rate limit ({base_text})'


def _format_rate_limit_guidance(rate_kind, retry_after) -> str:
    """Format actionable guidance for rate limit errors."""
    from backend.inference.exceptions import RateLimitKind

    kind_value = getattr(rate_kind, 'value', str(rate_kind)) if rate_kind else None

    if kind_value == RateLimitKind.RPD.value:
        return (
            '🎯 Next steps: '
            '1) Wait until midnight UTC for quota to reset, OR '
            '2) Add credits at https://openrouter.ai/credits to unlock 1000 requests/day, OR '
            '3) Switch to a different model in /settings.'
        )
    elif kind_value == RateLimitKind.RPM.value:
        if retry_after:
            return f'Waiting {retry_after:.0f}s before automatic retry...'
        return 'Waiting ~1 minute before retrying (per-minute limit).'
    elif kind_value == RateLimitKind.TPM.value:
        if retry_after:
            return f'Waiting {retry_after:.0f}s for token quota to refresh...'
        return 'Waiting for token quota to refresh...'
    else:
        return (
            'Will retry automatically. If this persists, check your provider dashboard.'
        )
