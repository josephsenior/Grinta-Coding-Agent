"""Step prerequisite checks for SessionOrchestrator."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.enums import RecallType
from backend.core.schemas import AgentState

if TYPE_CHECKING:
    from backend.orchestration.services.orchestration_context import OrchestrationContext


class StepPrerequisiteService:
    """Ensures the controller is allowed to execute another step."""

    def __init__(self, context: OrchestrationContext) -> None:
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
                recall_type = getattr(pending, "recall_type", None)
                # WORKSPACE_CONTEXT recall (first user message) loads critical
                # playbook and workspace information.  Block stepping until this
                # finishes so the LLM always has full context before acting.
                # KNOWLEDGE recalls (follow-up messages) are enrichments only —
                # the agent already has established context so concurrent
                # stepping is safe and keeps the loop responsive.
                if recall_type == RecallType.WORKSPACE_CONTEXT:
                    controller.log(
                        "debug",
                        "Blocking step while WORKSPACE_CONTEXT recall loads critical context",
                        extra={"msg_type": "STEP_BLOCKED_RECALL_CONTEXT"},
                    )
                    return False
                controller.log(
                    "debug",
                    "Allowing step while KNOWLEDGE RecallAction runs in background",
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
