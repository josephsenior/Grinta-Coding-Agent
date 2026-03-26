"""Service for validating task completion before allowing agent finish."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.core.logger import forge_logger as logger  # noqa: E402
from backend.core.schemas import AgentState  # noqa: E402
from backend.events import EventSource  # noqa: E402
from backend.events.action.agent import PlaybookFinishAction  # noqa: E402

if TYPE_CHECKING:
    from backend.controller.services.controller_context import ControllerContext


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
        # Save any lessons learned before finishing
        await self._save_lessons_learned(action)

        if not await self._ensure_completion_validator_available(action):
            return False

        if await self._should_validate(action):
            if not await self._validate_and_handle(action):
                return False
        return True

    async def _save_lessons_learned(self, action: PlaybookFinishAction) -> None:
        """Persist lessons learned to a repository-level memory file."""
        outputs = getattr(action, "outputs", {})
        if not outputs or not isinstance(outputs, dict):
            return

        lesson = outputs.get("lessons_learned")
        if not lesson or not str(lesson).strip():
            return

        import os
        from datetime import datetime

        # Path to project-level session memory
        file_store = self._context.get_controller().config.file_store
        project_root = file_store.root if file_store else "."
        memories_path = os.path.join(project_root, ".Forge", "lessons.md")

        try:
            os.makedirs(os.path.dirname(memories_path), exist_ok=True)

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            initial_task = self._context.get_controller()._get_initial_task()
            summary = initial_task.description[:100] if initial_task else "Task"

            entry = (
                f"\n## {timestamp} — {summary}\n"
                f"{lesson}\n"
            )

            with open(memories_path, "a", encoding="utf-8") as f:
                f.write(entry)

            logger.info("Saved lessons learned to %s", memories_path)
        except Exception as e:
            logger.warning("Failed to save lessons learned: %s", e)

    async def _emit_finish_block(
        self,
        message: str,
        error_id: str,
        *,
        cause_action: Any | None = None,
    ) -> bool:
        from backend.events.observation import ErrorObservation
        from backend.events.observation_cause import attach_observation_cause

        controller = self._context.get_controller()
        error_obs = ErrorObservation(content=message, error_id=error_id)
        attach_observation_cause(
            error_obs,
            cause_action,
            context="task_validation_service.finish_block",
        )
        controller.event_stream.add_event(error_obs, EventSource.ENVIRONMENT)

        if controller.state.agent_state != AgentState.RUNNING:
            await controller.set_agent_state_to(AgentState.RUNNING)
        return False

    async def _ensure_completion_validator_available(
        self, action: PlaybookFinishAction
    ) -> bool:
        """Fail closed when completion validation is enabled but validator is missing."""
        if getattr(action, "force_finish", False):
            return True

        controller = self._context.get_controller()
        validator = getattr(controller, "task_validator", None)
        if validator is not None:
            return True

        agent = getattr(controller, "agent", None)
        config = getattr(agent, "config", None) if agent else None
        enabled_raw = getattr(config, "enable_completion_validation", False)
        completion_validation_enabled = isinstance(enabled_raw, bool) and enabled_raw
        if not completion_validation_enabled:
            return True

        logger.warning(
            "Finish blocked: completion validation is enabled but no validator is configured"
        )
        return await self._emit_finish_block(
            "⚠️ FINISH BLOCKED: Completion validation is enabled but the validator is unavailable. "
            "Please continue working or retry once validation is restored.",
            error_id="TASK_VALIDATOR_UNAVAILABLE",
            cause_action=action,
        )

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
            await self._handle_failure(action, validation)
            return False

        logger.info("Task completion validation passed: %s", validation.reason)
        return True

    async def _handle_failure(
        self, action: PlaybookFinishAction, validation: Any
    ) -> None:
        """Emit an error observation and resume the agent on validation failure."""
        from backend.events.observation import ErrorObservation
        from backend.events.observation_cause import attach_observation_cause

        controller = self._context.get_controller()
        logger.warning("Task completion validation failed: %s", validation.reason)

        feedback = self._build_feedback(validation)
        error_obs = ErrorObservation(
            content=feedback,
            error_id="TASK_VALIDATION_FAILED",
        )
        attach_observation_cause(
            error_obs,
            action,
            context="task_validation_service.validation_failed",
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
