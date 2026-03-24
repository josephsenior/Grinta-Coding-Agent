"""Step readiness guards around circuit breaker and stuck detection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.logger import forge_logger as logger
from backend.core.schemas import AgentState
from backend.events import EventSource

from backend.events.action import FileEditAction, FileWriteAction
from backend.events.observation import ErrorObservation

if TYPE_CHECKING:
    from backend.controller.services.controller_context import ControllerContext


class StepGuardService:
    """Ensures controller steps are safe w.r.t. circuit breaker and stuck detection."""

    def __init__(self, context: ControllerContext) -> None:
        self._context = context

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
        cb_service = getattr(controller, "circuit_breaker_service", None)
        if not cb_service:
            return True

        result = cb_service.check()
        if not result or not result.tripped:
            return True

        # Circuit breaker only emits 'stop' for stuck detections now.
        # Step guard handles all recovery messaging separately.
        logger.error("Circuit breaker tripped: %s", result.reason)
        error_obs = ErrorObservation(
            content=(
                f"CIRCUIT BREAKER TRIPPED: {result.reason}\n\n"
                f"Action: {result.action.upper()}\n\n"
                f"{result.recommendation}"
            ),
            error_id="CIRCUIT_BREAKER_TRIPPED",
        )
        controller.event_stream.add_event(error_obs, EventSource.ENVIRONMENT)

        target_state = (
            AgentState.STOPPED if result.action == "stop" else AgentState.PAUSED
        )
        await controller.set_agent_state_to(target_state)
        return False

    async def _handle_stuck_detection(self, controller) -> bool:
        stuck_service = getattr(controller, "stuck_service", None)
        if not stuck_service:
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
            cb_service.record_stuck_detection()

        # Inject a replan directive; let the circuit breaker handle
        # escalation and eventual stopping.
        logger.warning("Stuck detected — injecting replan directive")
        self._inject_replan_directive(controller)
        return True

    @staticmethod
    def _normalize_path(p: str) -> str:
        """Normalize a file path for comparison: strip /workspace/ prefix, collapse separators."""
        p = p.replace("\\", "/").strip("/")
        if p.startswith("workspace/"):
            p = p[len("workspace/"):]
        return p.strip("/")

    def _inject_replan_directive(self, controller) -> None:
        """Inject a directive that forces the LLM to take real action.

        Uses ErrorObservation (rendered as role='user') so the message actually
        reaches the LLM.  SystemMessageAction is silently dropped by
        _dedupe_system_messages in conversation_memory.
        """
        state = getattr(controller, "state", None)
        history = getattr(state, "history", []) if state else []

        created_files = self._collect_created_files(history)
        msg, planning = self._build_stuck_recovery_message(created_files)

        error_obs = ErrorObservation(content=msg, error_id="STUCK_LOOP_RECOVERY")
        controller.event_stream.add_event(error_obs, EventSource.ENVIRONMENT)

        if state and hasattr(state, "set_planning_directive"):
            state.set_planning_directive(planning, source="StepGuardService")

    def _collect_created_files(self, history: list) -> set[str]:
        """Collect normalized paths of files created via FileWrite/FileEdit."""
        created = set()
        for e in history:
            if isinstance(e, (FileWriteAction, FileEditAction)):
                p = getattr(e, "path", "") or ""
                if p:
                    created.add(self._normalize_path(p))
        return created

    def _build_stuck_recovery_message(
        self,
        created_files: set[str],
    ) -> tuple[str, str]:
        """Build a generic stuck recovery message without task-text heuristics."""
        created_str = ", ".join(sorted(created_files))
        if created_files:
            return (
                "STUCK LOOP DETECTED — You are repeating actions without progress.\n"
                f"Files already touched in this session: {created_str}.\n"
                "Do NOT assume the task is complete based on file names alone.\n"
                "YOUR VERY NEXT ACTION MUST BE: perform one concrete unfinished task step, "
                "or verify the current state before changing course.",
                "STUCK RECOVERY: stop repeating, verify current state, then do the next unfinished step.",
            )
        return (
            "STUCK LOOP DETECTED — You are repeating actions without progress.\n"
            "MANDATORY RECOVERY:\n"
            "1. Stop repeating the same read-only or no-op action.\n"
            "2. Verify the current state using a concrete tool result.\n"
            "3. Execute one specific unfinished step.\n"
            "YOUR VERY NEXT ACTION MUST BE a real progress-making action.",
            "STUCK RECOVERY: verify state, then make one concrete next-step action.",
        )
