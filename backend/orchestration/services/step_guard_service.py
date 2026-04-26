"""Step readiness guards around circuit breaker and stuck detection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.core.logger import app_logger as logger
from backend.core.schemas import AgentState
from backend.ledger import EventSource
from backend.ledger.action import (
    CmdRunAction,
    FileEditAction,
    FileReadAction,
    FileWriteAction,
    LspQueryAction,
    RecallAction,
    TerminalReadAction,
    TerminalRunAction,
)
from backend.ledger.observation import CmdOutputObservation, ErrorObservation
from backend.ledger.observation.files import FileEditObservation, FileWriteObservation
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


def _pending_action_for_observation_cause(controller: "SessionOrchestrator") -> object | None:
    """Current pending action (if any) for correlating guard observations."""
    services = getattr(controller, "services", None)
    svc = getattr(services, "pending_action", None) if services is not None else None
    if svc is None:
        svc = getattr(controller, "pending_action_service", None)
    if svc is not None:
        return svc.get()
    return getattr(controller, "_pending_action", None)


def _clear_agent_queued_actions(controller: "SessionOrchestrator", reason: str) -> None:
    """Clear queued agent actions when recovery requires a hard strategy reset."""
    agent = getattr(controller, "agent", None)
    clear_fn = getattr(agent, "clear_queued_actions", None)
    if callable(clear_fn):
        clear_fn(reason=reason)


class StepGuardService:
    """Ensures controller steps are safe w.r.t. circuit breaker and stuck detection."""

    _WARNING_TRIP_COUNTS_KEY = "__step_guard_warning_trip_counts"
    _REPLAN_REQUIRED_KEY = "__step_guard_replan_required"
    _VERIFICATION_REQUIRED_KEY = "__step_guard_verification_required"

    def __init__(self, context: OrchestrationContext) -> None:
        self._context = context

    def _warning_trip_enabled(self) -> bool:
        cfg = getattr(self._context, "agent_config", None)
        if cfg is None:
            return True
        return bool(getattr(cfg, "warning_first_trip_enabled", True))

    def _warning_trip_limit(self) -> int:
        cfg = getattr(self._context, "agent_config", None)
        if cfg is None:
            return 3
        val = getattr(cfg, "warning_first_trip_limit", 3)
        try:
            return max(1, int(val))
        except Exception:
            return 3

    def _warning_trip_key(self, result: Any) -> str:
        reason = str(getattr(result, "reason", "unknown") or "unknown")
        action = str(getattr(result, "action", "unknown") or "unknown")
        return f"{action}:{reason}"

    def _record_warning_trip(self, controller: "SessionOrchestrator", result: Any) -> int:
        state: "State | None" = getattr(controller, "state", None)
        if state is None:
            return 1

        counts: dict[str, Any] = state.extra_data.get(self._WARNING_TRIP_COUNTS_KEY, {})

        key = self._warning_trip_key(result)
        count = int(counts.get(key, 0) or 0) + 1
        counts[key] = count

        # Keep extra_data as the source of truth even when set_extra is mocked.
        state.extra_data[self._WARNING_TRIP_COUNTS_KEY] = counts

        if hasattr(state, "set_extra"):
            state.set_extra(
                self._WARNING_TRIP_COUNTS_KEY, counts, source="StepGuardService"
            )

        return count

    def _emit_warning_trip_observation(
        self, controller: "SessionOrchestrator", result: Any, warning_count: int, limit: int
    ) -> None:
        reason = str(getattr(result, "reason", "unknown") or "unknown")
        action = str(getattr(result, "action", "pause") or "pause").upper()
        recommendation = str(getattr(result, "recommendation", "") or "")
        content = (
            "CIRCUIT BREAKER WARNING\n\n"
            f"Reason: {reason}\n"
            f"Action if escalated: {action}\n"
            f"Recommendation: {recommendation}\n"
            "You must change strategy now.\n"
            f"Warning attempt: {warning_count}/{limit}"
        )
        GuardBus.emit(
            controller,
            CIRCUIT_WARNING,
            "CIRCUIT_BREAKER_WARNING",
            content,
            "CIRCUIT WARNING: change strategy immediately; avoid repeating failed pattern; produce one concrete progress action next.",
            cause=_pending_action_for_observation_cause(controller),
            cause_context="step_guard.circuit_warning",
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

    def _get_replan_flag(self, controller: "SessionOrchestrator") -> bool:
        state: "State | None" = getattr(controller, "state", None)
        if state is None:
            return False
        extra: dict[str, Any] = getattr(state, "extra_data", {})
        return bool(extra.get(self._REPLAN_REQUIRED_KEY, False))

    def _set_replan_flag(self, controller: "SessionOrchestrator", value: bool) -> None:
        state: "State | None" = getattr(controller, "state", None)
        if state is None:
            return
        state.extra_data[self._REPLAN_REQUIRED_KEY] = bool(value)
        if hasattr(state, "set_extra"):
            state.set_extra(
                self._REPLAN_REQUIRED_KEY, bool(value), source="StepGuardService"
            )

    def _set_verification_requirement(
        self, controller: "SessionOrchestrator", requirement: dict[str, Any] | None
    ) -> None:
        state: "State | None" = getattr(controller, "state", None)
        if state is None:
            return
        state.extra_data[self._VERIFICATION_REQUIRED_KEY] = requirement
        if hasattr(state, "set_extra"):
            state.set_extra(
                self._VERIFICATION_REQUIRED_KEY,
                requirement,
                source="StepGuardService",
            )

    async def _check_circuit_breaker(self, controller: "SessionOrchestrator") -> bool | None:
        cb_service = getattr(controller, "circuit_breaker_service", None)
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
                    "Circuit breaker warning-only trip (%s/%s): %s",
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
        logger.error("Circuit breaker tripped: %s", result.reason)
        _state = getattr(controller, "state", None)
        # If action is switch_context, don't stop the agent, just force a new prompt directive
        if getattr(result, "action", "") == "switch_context":
            content = (
                f"CIRCUIT BREAKER FORCED STRATEGY SWITCH: {result.reason}\n\n"
                f"{result.recommendation}"
            )
            GuardBus.emit(
                controller,
                CIRCUIT_WARNING,
                "CIRCUIT_BREAKER_FORCED_SWITCH",
                content,
                "STRATEGY SWITCH REQUIRED: You must use a different tool or strategy now.",
                cause=_pending_action_for_observation_cause(controller),
                cause_context="step_guard.forced_switch",
            )
            _clear_agent_queued_actions(
                controller, "Forced strategy switch due to deterministic failures"
            )
            return True

        error_obs = ErrorObservation(
            content=(
                f"CIRCUIT BREAKER TRIPPED: {result.reason}\n\n"
                f"Action: {result.action.upper()}\n\n"
                f"{result.recommendation}"
            ),
            error_id="CIRCUIT_BREAKER_TRIPPED",
        )
        attach_observation_cause(
            error_obs,
            _pending_action_for_observation_cause(controller),
            context="step_guard.circuit_tripped",
        )
        controller.event_stream.add_event(error_obs, EventSource.ENVIRONMENT)

        target_state = (
            AgentState.STOPPED if result.action == "stop" else AgentState.PAUSED
        )
        await controller.set_agent_state_to(target_state)
        return False

    async def _handle_stuck_detection(self, controller: "SessionOrchestrator") -> bool:
        stuck_service = getattr(controller, "stuck_service", None)
        if not stuck_service:
            return True

        # Deterministic control-state transition: once stuck is detected,
        # force one planner re-entry turn before normal action flow resumes.
        if self._get_replan_flag(controller):
            self._set_replan_flag(controller, False)
            return True

        # Always compute and expose the repetition score for proactive self-correction
        rep_score = stuck_service.compute_repetition_score()
        state = getattr(controller, "state", None)
        if state and hasattr(state, "turn_signals"):
            state.turn_signals.repetition_score = rep_score

        if not stuck_service.is_stuck():
            return True

        cb_service = getattr(controller, "circuit_breaker_service", None)
        if cb_service:
            # Record each stuck turn so the circuit breaker can escalate and
            # stop persistent loops instead of warning indefinitely.
            cb_service.record_stuck_detection()

        # Inject a replan directive; let the circuit breaker handle
        # escalation and eventual stopping.
        logger.warning("Stuck detected — injecting replan directive")
        self._set_replan_flag(controller, True)
        self._inject_replan_directive(controller)
        return False

    @staticmethod
    def _normalize_path(p: str) -> str:
        """Normalize a file path for comparison: strip /workspace/ prefix, collapse separators."""
        p = p.replace("\\", "/").strip("/")
        if p.startswith("workspace/"):
            p = p[len("workspace/") :]
        return p.strip("/")

    def _inject_replan_directive(self, controller: "SessionOrchestrator") -> None:
        """Inject a directive that forces the LLM to take real action.

        Uses ErrorObservation (rendered as role='user') so the message actually
        reaches the LLM.  SystemMessageAction is silently dropped by
        _dedupe_system_messages in conversation_memory.
        """
        state = getattr(controller, "state", None)
        history = getattr(state, "history", []) if state else []

        _clear_agent_queued_actions(controller, reason="stuck_loop_recovery")

        created_files = self._collect_created_files(history)
        msg, planning, verification_requirement = self._build_stuck_recovery_message(
            created_files, history
        )

        if verification_requirement is not None:
            self._set_verification_requirement(controller, verification_requirement)

        GuardBus.emit(
            controller,
            STUCK,
            "STUCK_LOOP_RECOVERY",
            msg,
            planning,
            cause=_pending_action_for_observation_cause(controller),
            cause_context="step_guard.stuck_recovery",
        )

    def _collect_created_files(self, history: list[Any]) -> set[str]:
        """Collect normalized paths of files created via FileWrite/FileEdit."""
        created: set[str] = set()
        for e in history:
            if isinstance(e, (FileWriteAction, FileEditAction)):
                p = getattr(e, "path", "") or ""
                if p:
                    created.add(self._normalize_path(p))
        return created

    def _build_stuck_recovery_message(
        self,
        created_files: set[str],
        history: list[Any],
    ) -> tuple[str, str, dict[str, Any] | None]:
        """Build a generic stuck recovery message without task-text heuristics."""
        verification_requirement = self._build_verification_requirement(history)
        recent_errors = [
            (getattr(e, "content", "") or "")
            for e in history[-12:]
            if isinstance(e, ErrorObservation)
        ]
        text_editor_hits = sum(
            1
            for content in recent_errors
            if "text_editor" in content.lower()
            or "corrupt patch" in content.lower()
            or "patch failed to apply" in content.lower()
            or "[text_editor_guidance]" in content.lower()
        )
        if text_editor_hits >= 2:
            return (
                "STUCK LOOP DETECTED — repeated text_editor failures were detected.\n"
                "MANDATORY NEXT ACTIONS:\n"
                "1. Read the target file again with read_file to refresh exact context lines.\n"
                "2. Retry text_editor once with corrected unified diff context.\n"
                "3. If it fails again, switch to a different edit strategy instead of retrying text_editor.\n"
                "Do NOT emit another near-identical text_editor call without new file evidence.",
                "STUCK RECOVERY: read_file refresh, then one text_editor retry max, then switch strategy.",
                verification_requirement,
            )

        if verification_requirement is not None:
            path_list: list[Any] = list(verification_requirement.get("paths") or [])
            files_text = ", ".join(
                    str(path) for path in path_list if str(path).strip()
                )
            failure_text = str(
                verification_requirement.get("observed_failure")
                or "Recent failing feedback still contradicts the last edit attempt."
            ).strip()
            if not files_text:
                files_text = "recently touched files"
            return (
                "STUCK LOOP DETECTED — recent file changes were followed by failing feedback.\n"
                f"Files to reconcile: {files_text}.\n"
                f"Latest failing feedback: {failure_text}\n"
                "MANDATORY NEXT ACTIONS:\n"
                "1. Read the actual file contents or rerun the focused failing check.\n"
                "2. Compare the fresh output to your last assumption.\n"
                "3. Only then emit another edit or finish action.\n"
                "Do NOT emit another write/edit or finish action until you have one fresh grounding result.",
                "STUCK RECOVERY: reconcile actual file/check state before any more edits or finish.",
                verification_requirement,
            )

        created_str = ", ".join(sorted(created_files))
        if created_files:
            return (
                "STUCK LOOP DETECTED — You are repeating actions without progress.\n"
                f"Files already touched in this session: {created_str}.\n"
                "Do NOT assume the task is complete based on file names alone.\n"
                "YOUR VERY NEXT ACTION MUST BE: perform one concrete unfinished task step, "
                "or verify the current state before changing course.",
                "STUCK RECOVERY: stop repeating, verify current state, then do the next unfinished step.",
                None,
            )
        return (
            "STUCK LOOP DETECTED — You are repeating actions without progress.\n"
            "MANDATORY RECOVERY:\n"
            "1. Stop repeating the same read-only or no-op action.\n"
            "2. Verify the current state using a concrete tool result.\n"
            "3. Execute one specific unfinished step.\n"
            "YOUR VERY NEXT ACTION MUST BE a real progress-making action.",
            "STUCK RECOVERY: verify state, then make one concrete next-step action.",
            None,
        )

    def _build_verification_requirement(self, history: list[Any]) -> dict[str, Any] | None:
        """Detect stale-state churn after a recent file mutation plus failing feedback."""
        return StepGuardService._build_verification_requirement_from_history(history)

    @staticmethod
    def _build_verification_requirement_from_history(
        history: list[Any],
    ) -> dict[str, Any] | None:
        """Static entry point so ActionExecutionService can call it without an instance."""
        recent_history = list(history[-18:])
        last_mutation_index = -1
        mutated_paths: list[str] = []

        for idx, event in enumerate(recent_history):
            if isinstance(event, FileEditAction):
                command = str(getattr(event, "command", "") or "").strip().lower()
                if command == "read_file":
                    continue
                path = getattr(event, "path", "") or ""
                if path:
                    mutated_paths.append(StepGuardService._normalize_path(path))
                last_mutation_index = idx
                continue
            if isinstance(
                event,
                (FileWriteAction, FileEditObservation, FileWriteObservation),
            ):
                path = getattr(event, "path", "") or ""
                if path:
                    mutated_paths.append(StepGuardService._normalize_path(path))
                last_mutation_index = idx

        if last_mutation_index < 0:
            return None

        failing_feedback: list[str] = []
        last_failure_index = -1
        ignored_error_ids = {
            "CIRCUIT_BREAKER_TRIPPED",
            "CIRCUIT_BREAKER_WARNING",
            "NULL_ACTION_LOOP",
            "STUCK_LOOP_RECOVERY",
            "VERIFICATION_REQUIRED",
        }

        for rel_idx, event in enumerate(recent_history[last_mutation_index + 1 :]):
            abs_idx = last_mutation_index + 1 + rel_idx
            if isinstance(event, ErrorObservation):
                error_id = str(getattr(event, "error_id", "") or "").strip().upper()
                if error_id in ignored_error_ids:
                    continue
                first_line = (
                    (getattr(event, "content", "") or "").splitlines()[0].strip()
                )
                if first_line:
                    failing_feedback.append(first_line)
                    last_failure_index = abs_idx
                continue
            if isinstance(event, CmdOutputObservation):
                exit_code = getattr(event, "exit_code", None)
                if exit_code in (None, 0, -1):
                    continue
                first_line = (
                    (getattr(event, "content", "") or "").splitlines()[0].strip()
                )
                if not first_line:
                    command = str(getattr(event, "command", "") or "").strip()
                    first_line = (
                        f'{command or "Command"} failed with exit code {exit_code}'
                    )
                failing_feedback.append(first_line)
                last_failure_index = abs_idx

        if not mutated_paths or not failing_feedback:
            return None

        # If the agent already responded to the failure with a grounding action
        # (file read, command run, read_file) that appears AFTER the last failure
        # in history, the evidence has been investigated — don't re-block the
        # same stale failure indefinitely.
        if last_failure_index >= 0:
            for event in recent_history[last_failure_index + 1 :]:
                if isinstance(
                    event,
                    (
                        FileReadAction,
                        CmdRunAction,
                        LspQueryAction,
                        RecallAction,
                        TerminalReadAction,
                        TerminalRunAction,
                    ),
                ):
                    return None
                if isinstance(event, FileEditAction):
                    command = str(getattr(event, "command", "") or "").strip().lower()
                    if command == "read_file":
                        return None

        latest_failure = failing_feedback[-1]
        if len(latest_failure) > 180:
            latest_failure = latest_failure[:179].rstrip() + "…"

        return {
            "reason": "recent_file_mutation_plus_failure",
            "paths": sorted({path for path in mutated_paths if path})[:6],
            "observed_failure": latest_failure,
        }
