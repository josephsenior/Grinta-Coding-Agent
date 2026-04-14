"""Step readiness guards around circuit breaker and stuck detection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.logger import app_logger as logger
from backend.core.schemas import AgentState
from backend.ledger import EventSource
from backend.ledger.action import FileEditAction, FileWriteAction
from backend.ledger.observation import ErrorObservation
from backend.ledger.observation_cause import attach_observation_cause

if TYPE_CHECKING:
    from backend.orchestration.services.orchestration_context import (
        OrchestrationContext,
    )


def _pending_action_for_observation_cause(controller) -> object | None:
    """Current pending action (if any) for correlating guard observations."""
    services = getattr(controller, 'services', None)
    svc = getattr(services, 'pending_action', None) if services is not None else None
    if svc is None:
        svc = getattr(controller, 'pending_action_service', None)
    if svc is not None:
        return svc.get()
    return getattr(controller, '_pending_action', None)


def _clear_agent_queued_actions(controller, reason: str) -> None:
    """Clear queued agent actions when recovery requires a hard strategy reset."""
    agent = getattr(controller, 'agent', None)
    clear_fn = getattr(agent, 'clear_queued_actions', None)
    if callable(clear_fn):
        clear_fn(reason=reason)


class StepGuardService:
    """Ensures controller steps are safe w.r.t. circuit breaker and stuck detection."""

    _WARNING_TRIP_COUNTS_KEY = '__step_guard_warning_trip_counts'

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

    def _warning_trip_key(self, result) -> str:
        reason = str(getattr(result, 'reason', 'unknown') or 'unknown')
        action = str(getattr(result, 'action', 'unknown') or 'unknown')
        return f'{action}:{reason}'

    def _record_warning_trip(self, controller, result) -> int:
        state = getattr(controller, 'state', None)
        if state is None:
            return 1

        if not hasattr(state, 'extra_data') or not isinstance(state.extra_data, dict):
            state.extra_data = {}

        counts = state.extra_data.get(self._WARNING_TRIP_COUNTS_KEY, {})
        if not isinstance(counts, dict):
            counts = {}

        key = self._warning_trip_key(result)
        count = int(counts.get(key, 0)) + 1
        counts[key] = count

        # Keep extra_data as the source of truth even when set_extra is mocked.
        state.extra_data[self._WARNING_TRIP_COUNTS_KEY] = counts

        if hasattr(state, 'set_extra'):
            state.set_extra(
                self._WARNING_TRIP_COUNTS_KEY, counts, source='StepGuardService'
            )

        return count

    def _emit_warning_trip_observation(
        self, controller, result, warning_count: int, limit: int
    ) -> None:
        reason = str(getattr(result, 'reason', 'unknown') or 'unknown')
        action = str(getattr(result, 'action', 'pause') or 'pause').upper()
        recommendation = str(getattr(result, 'recommendation', '') or '')
        content = (
            'CIRCUIT BREAKER WARNING\n\n'
            f'Reason: {reason}\n'
            f'Action if escalated: {action}\n'
            f'Recommendation: {recommendation}\n'
            'You must change strategy now.\n'
            f'Warning attempt: {warning_count}/{limit}'
        )
        warning_obs = ErrorObservation(
            content=content,
            error_id='CIRCUIT_BREAKER_WARNING',
        )
        attach_observation_cause(
            warning_obs,
            _pending_action_for_observation_cause(controller),
            context='step_guard.circuit_warning',
        )
        controller.event_stream.add_event(warning_obs, EventSource.ENVIRONMENT)

        state = getattr(controller, 'state', None)
        if state and hasattr(state, 'set_planning_directive'):
            state.set_planning_directive(
                'CIRCUIT WARNING: change strategy immediately; avoid repeating failed pattern; produce one concrete progress action next.',
                source='StepGuardService',
            )

    async def ensure_can_step(self) -> bool:
        """Return False if circuit breaker/stuck detection block execution."""
        controller = self._context.get_controller()
        # Circuit breaker is authoritative for pause/stop decisions.
        # Stuck detection runs only if stepping is still allowed, where it can
        # inject recovery guidance without overriding a hard stop/pause.
        if await self._check_circuit_breaker(controller) is False:
            return False
        if await self._handle_stuck_detection(controller) is False:
            return False
        return True

    async def _check_circuit_breaker(self, controller) -> bool | None:
        cb_service = getattr(controller, 'circuit_breaker_service', None)
        if not cb_service:
            return True

        result = cb_service.check()
        if not result or not result.tripped:
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
        state = getattr(controller, 'state', None)
        # If action is switch_context, don't stop the agent, just force a new prompt directive
        if getattr(result, 'action', '') == 'switch_context':
            content = (
                f'CIRCUIT BREAKER FORCED STRATEGY SWITCH: {result.reason}\n\n'
                f'{result.recommendation}'
            )
            obs = ErrorObservation(content=content, error_id='CIRCUIT_BREAKER_FORCED_SWITCH')
            attach_observation_cause(obs, _pending_action_for_observation_cause(controller), context='step_guard.forced_switch')
            controller.event_stream.add_event(obs, EventSource.ENVIRONMENT)
            if state and hasattr(state, 'set_planning_directive'):
                state.set_planning_directive(
                    'STRATEGY SWITCH REQUIRED: You must use a different tool or strategy now.',
                    source='StepGuardService',
                )
            _clear_agent_queued_actions(controller, 'Forced strategy switch due to deterministic failures')
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

        target_state = (
            AgentState.STOPPED if result.action == 'stop' else AgentState.PAUSED
        )
        await controller.set_agent_state_to(target_state)
        return False

    async def _handle_stuck_detection(self, controller) -> bool:
        stuck_service = getattr(controller, 'stuck_service', None)
        if not stuck_service:
            return True

        # Always compute and expose the repetition score for proactive self-correction
        rep_score = stuck_service.compute_repetition_score()
        state = getattr(controller, 'state', None)
        if state and hasattr(state, 'turn_signals'):
            state.turn_signals.repetition_score = rep_score

        if not stuck_service.is_stuck():
            return True

        cb_service = getattr(controller, 'circuit_breaker_service', None)
        if cb_service:
            # Record each stuck turn so the circuit breaker can escalate and
            # stop persistent loops instead of warning indefinitely.
            cb_service.record_stuck_detection()

        # Inject a replan directive; let the circuit breaker handle
        # escalation and eventual stopping.
        logger.warning('Stuck detected — injecting replan directive')
        self._inject_replan_directive(controller)
        return True

    @staticmethod
    def _normalize_path(p: str) -> str:
        """Normalize a file path for comparison: strip /workspace/ prefix, collapse separators."""
        p = p.replace('\\', '/').strip('/')
        if p.startswith('workspace/'):
            p = p[len('workspace/') :]
        return p.strip('/')

    def _inject_replan_directive(self, controller) -> None:
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

        error_obs = ErrorObservation(content=msg, error_id='STUCK_LOOP_RECOVERY')
        attach_observation_cause(
            error_obs,
            _pending_action_for_observation_cause(controller),
            context='step_guard.stuck_recovery',
        )
        controller.event_stream.add_event(error_obs, EventSource.ENVIRONMENT)

        if state and hasattr(state, 'set_planning_directive'):
            state.set_planning_directive(planning, source='StepGuardService')

    def _collect_created_files(self, history: list) -> set[str]:
        """Collect normalized paths of files created via FileWrite/FileEdit."""
        created = set()
        for e in history:
            if isinstance(e, (FileWriteAction, FileEditAction)):
                p = getattr(e, 'path', '') or ''
                if p:
                    created.add(self._normalize_path(p))
        return created

    def _build_stuck_recovery_message(
        self,
        created_files: set[str],
        history: list,
    ) -> tuple[str, str]:
        """Build a generic stuck recovery message without task-text heuristics."""
        recent_errors = [
            (getattr(e, 'content', '') or '')
            for e in history[-12:]
            if isinstance(e, ErrorObservation)
        ]
        str_replace_editor_hits = sum(
            1
            for content in recent_errors
            if 'str_replace_editor' in content.lower()
            or 'corrupt patch' in content.lower()
            or 'patch failed to apply' in content.lower()
            or '[str_replace_editor_guidance]' in content.lower()
        )
        if str_replace_editor_hits >= 2:
            return (
                'STUCK LOOP DETECTED — repeated str_replace_editor failures were detected.\n'
                'MANDATORY NEXT ACTIONS:\n'
                '1. Read the target file again with read_file to refresh exact context lines.\n'
                '2. Retry str_replace_editor once with corrected unified diff context.\n'
                '3. If it fails again, switch to a different edit strategy instead of retrying str_replace_editor.\n'
                'Do NOT emit another near-identical str_replace_editor call without new file evidence.',
                'STUCK RECOVERY: read_file refresh, then one str_replace_editor retry max, then switch strategy.',
            )

        created_str = ', '.join(sorted(created_files))
        if created_files:
            return (
                'STUCK LOOP DETECTED — You are repeating actions without progress.\n'
                f'Files already touched in this session: {created_str}.\n'
                'Do NOT assume the task is complete based on file names alone.\n'
                'YOUR VERY NEXT ACTION MUST BE: perform one concrete unfinished task step, '
                'or verify the current state before changing course.',
                'STUCK RECOVERY: stop repeating, verify current state, then do the next unfinished step.',
            )
        return (
            'STUCK LOOP DETECTED — You are repeating actions without progress.\n'
            'MANDATORY RECOVERY:\n'
            '1. Stop repeating the same read-only or no-op action.\n'
            '2. Verify the current state using a concrete tool result.\n'
            '3. Execute one specific unfinished step.\n'
            'YOUR VERY NEXT ACTION MUST BE a real progress-making action.',
            'STUCK RECOVERY: verify state, then make one concrete next-step action.',
        )
