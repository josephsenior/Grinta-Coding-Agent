"""Step readiness guards around circuit breaker and stuck detection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.core.agent_protocol import prepare_next_agent_step
from backend.core.constants import DEFAULT_STUCK_COOLDOWN_TURNS
from backend.core.interaction_modes import normalize_interaction_mode
from backend.core.logger import app_logger as logger
from backend.core.schemas import AgentState
from backend.ledger import EventSource
from backend.ledger.observation import ErrorObservation
from backend.ledger.observation_cause import attach_observation_cause
from backend.orchestration.services.guard_bus import (
    CIRCUIT_WARNING,
    STUCK,
    GuardBus,
)

if TYPE_CHECKING:
    from backend.orchestration.services.orchestration_context import (
        OrchestrationContext,
    )
    from backend.orchestration.session_orchestrator import SessionOrchestrator
    from backend.orchestration.state.state import State


def _pending_action_for_observation_cause(
    controller: 'SessionOrchestrator',
) -> object | None:
    """Current pending action (if any) for correlating guard observations."""
    services = getattr(controller, 'services', None)
    svc = getattr(services, 'pending_action', None) if services is not None else None
    if svc is None:
        svc = getattr(controller, 'pending_action_service', None)
    if svc is not None:
        return svc.get()
    return getattr(controller, '_pending_action', None)


def _controller_llm_stream_active(controller: 'SessionOrchestrator') -> bool:
    checker = getattr(controller, '_is_llm_stream_active', None)
    if not callable(checker):
        return False
    try:
        return bool(checker())
    except Exception:
        return False


def _controller_runtime_work_active(controller: 'SessionOrchestrator') -> bool:
    checker = getattr(controller, '_is_runtime_work_active', None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:
            return False
    pending_svc = getattr(getattr(controller, 'services', None), 'pending_action', None)
    if pending_svc is None:
        return False
    has_outstanding = getattr(pending_svc, 'has_outstanding', None)
    if not callable(has_outstanding):
        return False
    try:
        return bool(has_outstanding())
    except Exception:
        return False


def _clear_agent_queued_actions(controller: 'SessionOrchestrator', reason: str) -> None:
    """Clear queued agent actions when recovery requires a hard strategy reset."""
    agent = getattr(controller, 'agent', None)
    clear_fn = getattr(agent, 'clear_queued_actions', None)
    if callable(clear_fn):
        clear_fn(reason=reason)


class StepGuardService:
    """Ensures controller steps are safe w.r.t. circuit breaker and stuck detection."""

    _WARNING_TRIP_COUNTS_KEY = '__step_guard_warning_trip_counts'
    _REPLAN_REQUIRED_KEY = '__step_guard_replan_required'
    _STUCK_COOLDOWN_KEY = '__step_guard_stuck_cooldown'

    def __init__(self, context: OrchestrationContext) -> None:
        self._context = context

    def _warning_trip_enabled(self) -> bool:
        cfg = getattr(self._context, 'agent_config', None)
        if cfg is None:
            return True
        return bool(getattr(cfg, 'warning_first_trip_enabled', True))

    def _warning_trip_limit(self) -> int:
        cfg = getattr(self._context, 'agent_config', None)
        if cfg is None:
            return 3
        val = getattr(cfg, 'warning_first_trip_limit', 3)
        try:
            return max(1, int(val))
        except Exception:
            return 3

    def _warning_trip_key(self, result: Any) -> str:
        reason = str(getattr(result, 'reason', 'unknown') or 'unknown')
        action = str(getattr(result, 'action', 'unknown') or 'unknown')
        return f'{action}:{reason}'

    def _record_warning_trip(
        self, controller: 'SessionOrchestrator', result: Any
    ) -> int:
        state: 'State | None' = getattr(controller, 'state', None)
        if state is None:
            return 1

        counts: dict[str, Any] = state.extra_data.get(self._WARNING_TRIP_COUNTS_KEY, {})

        key = self._warning_trip_key(result)
        count = int(counts.get(key, 0) or 0) + 1
        counts[key] = count

        # Keep extra_data as the source of truth even when set_extra is mocked.
        state.extra_data[self._WARNING_TRIP_COUNTS_KEY] = counts

        if hasattr(state, 'set_extra'):
            state.set_extra(
                self._WARNING_TRIP_COUNTS_KEY, counts, source='StepGuardService'
            )

        return count

    def _emit_warning_trip_observation(
        self,
        controller: 'SessionOrchestrator',
        result: Any,
        warning_count: int,
        limit: int,
    ) -> None:
        reason = str(getattr(result, 'reason', 'unknown') or 'unknown')
        content = (
            f'CIRCUIT_BREAKER_WARNING: {reason}. '
            f'Try a different approach. ({warning_count}/{limit})'
        )
        GuardBus.emit(
            controller,
            CIRCUIT_WARNING,
            'CIRCUIT_BREAKER_WARNING',
            content,
            f'CIRCUIT WARNING: {reason}; choose one concrete next action.',
            cause=_pending_action_for_observation_cause(controller),
            cause_context='step_guard.circuit_warning',
        )

    async def ensure_can_step(self) -> bool:
        """Return False if circuit breaker/stuck detection block execution."""
        controller = self._context.get_controller()
        self._prepare_agent_protocol_directive(controller)
        # Circuit breaker is authoritative for pause/stop decisions.
        # Stuck detection runs only if stepping is still allowed, where it can
        # inject recovery guidance without overriding a hard stop/pause.
        if await self._check_circuit_breaker(controller) is False:
            return False
        if await self._handle_stuck_detection(controller) is False:
            return False
        return True

    @staticmethod
    def _prepare_agent_protocol_directive(controller: 'SessionOrchestrator') -> None:
        state = getattr(controller, 'state', None)
        config = getattr(controller, 'config', None)
        mode = normalize_interaction_mode(getattr(config, 'mode', 'agent'))
        prepare_next_agent_step(state, mode)

    def _get_replan_flag(self, controller: 'SessionOrchestrator') -> bool:
        state: 'State | None' = getattr(controller, 'state', None)
        if state is None:
            return False
        extra: dict[str, Any] = getattr(state, 'extra_data', {})
        return bool(extra.get(self._REPLAN_REQUIRED_KEY, False))

    def _set_replan_flag(self, controller: 'SessionOrchestrator', value: bool) -> None:
        state: 'State | None' = getattr(controller, 'state', None)
        if state is None:
            return
        state.extra_data[self._REPLAN_REQUIRED_KEY] = bool(value)
        if hasattr(state, 'set_extra'):
            state.set_extra(
                self._REPLAN_REQUIRED_KEY, bool(value), source='StepGuardService'
            )

    async def _check_circuit_breaker(
        self, controller: 'SessionOrchestrator'
    ) -> bool | None:
        cb_service = getattr(controller, 'circuit_breaker_service', None)
        if not cb_service:
            return True

        # Feed the latest state into the circuit breaker so the watchdog
        # can read it without a direct controller reference.
        agent_state = controller.get_agent_state()
        if hasattr(cb_service, 'update_cached_state'):
            cb_service.update_cached_state(agent_state)

        result = cb_service.check()
        if not result or not result.tripped:
            # Even when the primary check passes, run the no-step-progress
            # watchdog.  This is a safety net for the rare case where
            # ``_step_request`` is not delivered to a step task.
            watchdog_result = await self._check_no_step_progress_watchdog(
                controller, cb_service, agent_state
            )
            if watchdog_result is not None:
                return watchdog_result
            return True

        if self._warning_trip_enabled():
            warning_count = self._record_warning_trip(controller, result)
            limit = self._warning_trip_limit()
            if warning_count <= limit:
                logger.warning(
                    'Circuit breaker warning-only trip (%s/%s): %s',
                    warning_count,
                    limit,
                    result.reason,
                )
                self._emit_warning_trip_observation(
                    controller,
                    result,
                    warning_count,
                    limit,
                )
                return True

        # Circuit breaker only emits 'stop' for stuck detections now.
        # Step guard handles all recovery messaging separately.
        logger.error('Circuit breaker tripped: %s', result.reason)
        _state = getattr(controller, 'state', None)
        # If action is switch_context, don't stop the agent, just force a new prompt directive
        if getattr(result, 'action', '') == 'switch_context':
            content = (
                f'CIRCUIT BREAKER FORCED STRATEGY SWITCH: {result.reason}\n\n'
                f'{result.recommendation}'
            )
            GuardBus.emit(
                controller,
                CIRCUIT_WARNING,
                'CIRCUIT_BREAKER_FORCED_SWITCH',
                content,
                'STRATEGY SWITCH REQUIRED: You must use a different tool or strategy now.',
                cause=_pending_action_for_observation_cause(controller),
                cause_context='step_guard.forced_switch',
            )
            _clear_agent_queued_actions(
                controller, 'Forced strategy switch due to deterministic failures'
            )
            return True

        error_obs = ErrorObservation(
            content=(
                f'CIRCUIT BREAKER TRIPPED: {result.reason}\n\n'
                f'Action: {result.action.upper()}\n\n'
                f'{result.recommendation}'
            ),
            error_id='CIRCUIT_BREAKER_TRIPPED',
        )
        attach_observation_cause(
            error_obs,
            _pending_action_for_observation_cause(controller),
            context='step_guard.circuit_tripped',
        )
        controller.event_stream.add_event(error_obs, EventSource.ENVIRONMENT)

        await controller.set_agent_state_to(AgentState.STOPPED)
        return False

    async def _check_no_step_progress_watchdog(
        self,
        controller: 'SessionOrchestrator',
        cb_service: object,
        agent_state: 'AgentState',
    ) -> bool | None:
        """Run the no-step-progress watchdog and handle its result.

        Returns ``None`` if the watchdog is disabled or not triggered.
        Returns ``True`` if the watchdog fired but auto-recovered.
        Returns ``False`` if the watchdog determined the agent is stuck and
        should be stopped.
        """
        watchdog_fn = getattr(cb_service, 'check_no_step_progress', None)
        if not callable(watchdog_fn):
            return None

        try:
            result = watchdog_fn(
                agent_state=agent_state,
                llm_stream_active=_controller_llm_stream_active(controller),
                runtime_work_active=_controller_runtime_work_active(controller),
            )
        except Exception as exc:
            logger.debug('No-step-progress watchdog raised: %s', exc, exc_info=True)
            return None

        if result is None:
            return None

        action = getattr(result, 'action', '')
        if action == 'auto_recover_once':
            logger.warning(
                'No step progress stall; scheduling recovery',
                extra={'msg_type': 'NO_STEP_PROGRESS_WATCHDOG'},
            )
            try:
                controller.schedule_step_soon()
            except Exception:
                pass
            return True  # keep stepping (auto-recover in progress)

        if action == 'stop':
            logger.error(
                'No step progress stall after auto-recover',
                extra={'msg_type': 'NO_STEP_PROGRESS_WATCHDOG'},
            )
            error_obs = ErrorObservation(
                content=(
                    'NO_STEP_PROGRESS: agent loop stalled in RUNNING state. '
                    f'Reason: {getattr(result, "reason", "unknown")}'
                ),
                error_id='NO_STEP_PROGRESS_WATCHDOG',
            )
            attach_observation_cause(
                error_obs,
                _pending_action_for_observation_cause(controller),
                context='step_guard.no_step_progress_watchdog',
            )
            controller.event_stream.add_event(error_obs, EventSource.ENVIRONMENT)
            try:
                await controller.set_agent_state_to(AgentState.ERROR)
            except Exception:
                pass
            return False

        return None

    async def _handle_stuck_detection(self, controller: 'SessionOrchestrator') -> bool:
        stuck_service = getattr(controller, 'stuck_service', None)
        if not stuck_service:
            return True

        if self._consume_replan_turn(controller):
            return True

        state = getattr(controller, 'state', None)
        # Only consume cooldown during the main step, not during batch-drain
        # sub-iterations.  Batch drain processes queued non-runnable actions
        # without LLM calls; consuming cooldown there burns through the
        # model's recovery turns before it gets a chance to act.
        if not getattr(controller, '_draining_batch', False):
            if self._consume_stuck_cooldown(state):
                return True

        rep_score = stuck_service.compute_repetition_score()
        self._set_repetition_score(state, rep_score)

        if not stuck_service.is_stuck():
            return True

        self._record_stuck_detection(controller)
        self._arm_stuck_cooldown(state)
        self._trigger_stuck_recovery(controller)
        return False

    def _consume_replan_turn(self, controller: 'SessionOrchestrator') -> bool:
        # Deterministic control-state transition: once stuck is detected,
        # force one planner re-entry turn before normal action flow resumes.
        if not self._get_replan_flag(controller):
            return False
        self._set_replan_flag(controller, False)
        return True

    def _consume_stuck_cooldown(self, state: 'State | None') -> bool:
        # Cooldown: after a stuck detection the model needs N uninterrupted turns
        # to act on the recovery directive.  Do not re-evaluate is_stuck() until
        # the cooldown has elapsed.
        #
        # Cooldown is consumed once per full step() cycle (not per _step_inner()
        # sub-iteration during batch drain) so the model gets the full cooldown
        # period of actual LLM turns. The callers gate this on draining_batch.
        if state is None:
            return False

        cooldown = int(
            (getattr(state, 'extra_data', {}) or {}).get(self._STUCK_COOLDOWN_KEY, 0)
        )
        if cooldown <= 0:
            return False

        new_cooldown = cooldown - 1
        state.extra_data[self._STUCK_COOLDOWN_KEY] = new_cooldown
        if hasattr(state, 'set_extra'):
            state.set_extra(
                self._STUCK_COOLDOWN_KEY,
                new_cooldown,
                source='StepGuardService',
            )
        logger.debug('Stuck cooldown active: %d turns remaining', new_cooldown)
        return True

    @staticmethod
    def _set_repetition_score(state: 'State | None', rep_score: float) -> None:
        if state is not None and hasattr(state, 'turn_signals'):
            state.turn_signals.repetition_score = rep_score

    @staticmethod
    def _record_stuck_detection(controller: 'SessionOrchestrator') -> None:
        cb_service = getattr(controller, 'circuit_breaker_service', None)
        if cb_service:
            cb_service.record_stuck_detection()

    def _arm_stuck_cooldown(self, state: 'State | None') -> None:
        if state is None:
            return
        state.extra_data[self._STUCK_COOLDOWN_KEY] = DEFAULT_STUCK_COOLDOWN_TURNS
        if hasattr(state, 'set_extra'):
            state.set_extra(
                self._STUCK_COOLDOWN_KEY,
                DEFAULT_STUCK_COOLDOWN_TURNS,
                source='StepGuardService',
            )

    def _trigger_stuck_recovery(self, controller: 'SessionOrchestrator') -> None:
        logger.warning('Stuck detected — injecting replan directive')
        self._set_replan_flag(controller, True)
        self._inject_replan_directive(controller)

    @staticmethod
    def _normalize_path(p: str) -> str:
        """Normalize a file path for comparison: strip /workspace/ prefix, collapse separators."""
        p = p.replace('\\', '/').strip('/')
        if p.startswith('workspace/'):
            p = p[len('workspace/') :]
        return p.strip('/')

    def _inject_replan_directive(self, controller: 'SessionOrchestrator') -> None:
        """Inject a directive that forces the LLM to take real action.

        Uses ErrorObservation (rendered as role='user') so the message actually
        reaches the LLM.  SystemMessageAction is silently dropped by
        _dedupe_system_messages in conversation_memory.
        """
        state = getattr(controller, 'state', None)
        history = getattr(state, 'history', []) if state else []

        _clear_agent_queued_actions(controller, reason='stuck_loop_recovery')

        created_files = self._collect_created_files(history)
        msg, planning = self._build_stuck_recovery_message(created_files, history)

        GuardBus.emit(
            controller,
            STUCK,
            'STUCK_LOOP_RECOVERY',
            msg,
            planning,
            cause=_pending_action_for_observation_cause(controller),
            cause_context='step_guard.stuck_recovery',
        )

    def _collect_created_files(self, history: list[Any]) -> set[str]:
        """Collect normalized paths of files created via file mutation actions."""
        from backend.ledger.action import FileEditAction

        created: set[str] = set()
        for e in history:
            if isinstance(e, FileEditAction):
                p = getattr(e, 'path', '') or ''
                if p:
                    created.add(self._normalize_path(p))
        return created

    def _build_stuck_recovery_message(
        self,
        created_files: set[str],
        history: list[Any],
    ) -> tuple[str, str]:
        """Build a generic stuck recovery message without task-text heuristics."""
        recent_errors = self._recent_error_contents(history)
        editor_message = self._editor_recovery_message(recent_errors)
        if editor_message is not None:
            return editor_message

        created_files_message = self._created_files_recovery_message(created_files)
        if created_files_message is not None:
            return created_files_message

        return (
            'STUCK_LOOP: repeating actions without progress.',
            'STUCK_LOOP: make one concrete progress action.',
        )

    @staticmethod
    def _recent_error_contents(history: list[Any]) -> list[str]:
        return [
            (getattr(event, 'content', '') or '')
            for event in history[-12:]
            if isinstance(event, ErrorObservation)
        ]

    @staticmethod
    def _editor_recovery_message(
        recent_errors: list[str],
    ) -> tuple[str, str] | None:
        symbol_hits = sum(
            1
            for content in recent_errors
            if 'symbol edit error' in content.lower()
            or 'symbol ' in content.lower()
            and 'not found' in content.lower()
            or '[editor_recovery_required]' in content.lower()
        )
        if symbol_hits >= 2:
            return (
                'STUCK_LOOP: repeated symbol/code-edit failures.',
                'STUCK_LOOP: refresh symbol context, then one targeted edit.',
            )

        file_edit_hits = sum(
            1
            for content in recent_errors
            if 'range edit failed' in content.lower()
            or 'stale line range' in content.lower()
            or '[file_edit_guidance]' in content.lower()
        )
        if file_edit_hits < 2:
            return None
        return (
            'STUCK_LOOP: repeated file-edit failures.',
            'STUCK_LOOP: refresh file context, then one targeted edit.',
        )

    @staticmethod
    def _created_files_recovery_message(
        created_files: set[str],
    ) -> tuple[str, str] | None:
        if not created_files:
            return None
        created_str = ', '.join(sorted(created_files))
        return (
            f'STUCK_LOOP: repeating actions without progress. '
            f'Files already touched: {created_str}.',
            'STUCK_LOOP: verify state, then one concrete next step.',
        )
