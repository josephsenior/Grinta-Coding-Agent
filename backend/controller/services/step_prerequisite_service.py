"""Step prerequisite checks for AgentController."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.schemas import AgentState

if TYPE_CHECKING:
    from backend.controller.services.controller_context import ControllerContext


class StepPrerequisiteService:
    """Ensures the controller is allowed to execute another step."""

    def __init__(self, context: ControllerContext) -> None:
        self._context = context

    def can_step(self) -> bool:
        controller = self._context.get_controller()
        if controller.get_agent_state() != AgentState.RUNNING:
            controller.log(
                "debug",
                f"Agent not stepping because state is {controller.get_agent_state()} (not RUNNING)",
                extra={"msg_type": "STEP_BLOCKED_STATE"},
            )
            return False

        pending = self._context.pending_action
        if pending:
            if type(pending).__name__ == "RecallAction":
                controller.log(
                    "debug",
                    "Allowing step while RecallAction runs in background",
                    extra={"msg_type": "STEP_ALLOWED_PENDING_RECALL"},
                )
                return True
            action_id = getattr(pending, "id", "unknown")
            action_type = type(pending).__name__
            controller.log(
                "debug",
                f"Agent not stepping because of pending action: {action_type} (id={action_id})",
                extra={"msg_type": "STEP_BLOCKED_PENDING_ACTION"},
            )
            return False

        return True
