"""Step readiness guards around circuit breaker and stuck detection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.exceptions import AgentStuckInLoopError
from backend.core.logger import forge_logger as logger
from backend.core.schemas import AgentState
from backend.events import EventSource
from backend.events.action import AgentThinkAction
from backend.events.observation import ErrorObservation

if TYPE_CHECKING:
    from backend.controller.services.controller_context import ControllerContext


class StepGuardService:
    """Ensures controller steps are safe w.r.t. circuit breaker and stuck detection."""

    _replan_attempts: int = 0
    _MAX_REPLAN_ATTEMPTS: int = 2

    def __init__(self, context: ControllerContext) -> None:
        self._context = context
        self._replan_attempts = 0

    async def ensure_can_step(self) -> bool:
        """Return False if circuit breaker/stuck detection block execution."""
        controller = self._context.get_controller()
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
            self._replan_attempts = 0
            return True

        cb_service = getattr(controller, "circuit_breaker_service", None)
        if cb_service:
            cb_service.record_stuck_detection()

        # Try replanning before escalating to error recovery.
        if self._replan_attempts < self._MAX_REPLAN_ATTEMPTS:
            self._replan_attempts += 1
            logger.warning(
                "Stuck detected — injecting replan directive (attempt %d/%d)",
                self._replan_attempts,
                self._MAX_REPLAN_ATTEMPTS,
            )
            self._inject_replan_directive(controller)
            return True

        # Replanning exhausted — fall back to the original error recovery path
        self._replan_attempts = 0
        await controller._react_to_exception(
            AgentStuckInLoopError("Agent got stuck in a loop")
        )
        return False

    def _inject_replan_directive(self, controller) -> None:
        """Inject a think action that forces the LLM to reassess its approach."""
        replan_think = AgentThinkAction(
            thought=(
                "🚨 STUCK LOOP DETECTED — Your last several actions achieved no progress. "
                "MANDATORY RECOVERY PROTOCOL:\n"
                "1. STOP repeating the same approach\n"
                "2. Analyze what went wrong — what error or non-progress pattern do you see?\n"
                "3. List 2-3 ALTERNATIVE strategies you haven't tried\n"
                "4. Pick the most promising one and execute it\n"
                "5. If the file you're editing has changed, use view to see current content first\n\n"
                "DO NOT repeat any action you've already tried. Change your strategy completely."
            )
        )
        controller.event_stream.add_event(replan_think, EventSource.AGENT)

        # Set a planning directive so the planner also nudges the LLM
        state = getattr(controller, "state", None)
        if state and hasattr(state, "set_planning_directive"):
            state.set_planning_directive(
                "STUCK RECOVERY: Your previous approach failed repeatedly. "
                "You MUST change strategy. Review errors with error_patterns() "
                "and update your plan with task_tracker(command='plan').",
                source="StepGuardService",
            )
