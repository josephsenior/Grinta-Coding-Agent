"""Step readiness guards around circuit breaker and stuck detection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.exceptions import AgentStuckInLoopError
from backend.core.logger import FORGE_logger as logger
from backend.core.schemas import AgentState
from backend.events import EventSource
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

        if not stuck_service.is_stuck():
            return True

        cb_service = getattr(controller, "circuit_breaker_service", None)
        if cb_service:
            cb_service.record_stuck_detection()

        await controller._react_to_exception(
            AgentStuckInLoopError("Agent got stuck in a loop")
        )
        return False
