"""Service for validating task completion before allowing agent finish."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.core.logger import FORGE_logger as logger
from backend.core.schemas import AgentState
from backend.events import EventSource

if TYPE_CHECKING:
    from backend.controller.services.controller_context import ControllerContext
    from backend.events.action.agent import PlaybookFinishAction


class TaskValidationService:
    """Validates agent task completion using a pluggable validator.

    Extracted from AgentController to keep the controller focused on
    orchestration while this service owns the validation decision logic.
    """

    def __init__(self, context: ControllerContext) -> None:
        self._context = context

    async def handle_finish(self, action: PlaybookFinishAction) -> bool:
        """Handle a finish action, validating completion if configured.

        Returns:
            True if finish should proceed (validation passed or not configured),
            False if validation failed and the agent should continue working.
        """
        if await self._should_validate(action):
            if not await self._validate_and_handle(action):
                return False
        return True

    # ── internals ───────────────────────────────────────────────────

    async def _should_validate(self, action: PlaybookFinishAction) -> bool:
        """Check if task completion should be validated."""
        controller = self._context.get_controller()
        validator = getattr(controller, "task_validator", None)
        return bool(validator) and not getattr(action, "force_finish", False)

    async def _validate_and_handle(self, action: PlaybookFinishAction) -> bool:
        """Run the validator and handle the result.

        Returns True if passed, False if failed.
        """
        controller = self._context.get_controller()
        task = controller._get_initial_task()
        if not task:
            return True

        validator = getattr(controller, "task_validator", None)
        if validator is None:
            return True

        logger.info("Validating task completion before finishing...")
        validation = await validator.validate_completion(task, controller.state)

        if not validation.passed:
            await self._handle_failure(validation)
            return False

        logger.info("Task completion validation passed: %s", validation.reason)
        return True

    async def _handle_failure(self, validation: Any) -> None:
        """Emit an error observation and resume the agent on validation failure."""
        from backend.events.observation import ErrorObservation

        controller = self._context.get_controller()
        logger.warning("Task completion validation failed: %s", validation.reason)

        feedback = self._build_feedback(validation)
        error_obs = ErrorObservation(
            content=feedback,
            error_id="TASK_VALIDATION_FAILED",
        )
        controller.event_stream.add_event(error_obs, EventSource.ENVIRONMENT)

        if controller.state.agent_state != AgentState.RUNNING:
            await controller.set_agent_state_to(AgentState.RUNNING)

    @staticmethod
    def _build_feedback(validation: Any) -> str:
        """Build a human-readable feedback message from a validation result."""
        feedback = f"TASK NOT COMPLETE: {validation.reason}\n\nConfidence: {validation.confidence:.1%}\n"

        if validation.missing_items:
            feedback += "\nMissing items:\n" + "\n".join(
                f"- {item}" for item in validation.missing_items
            )

        if validation.suggestions:
            feedback += "\n\nSuggestions:\n" + "\n".join(
                f"- {sug}" for sug in validation.suggestions
            )

        feedback += "\n\nPlease continue working to complete the task."
        return feedback
