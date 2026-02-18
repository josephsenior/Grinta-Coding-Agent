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
        self._test_check_warned = False

    async def handle_finish(self, action: PlaybookFinishAction) -> bool:
        """Handle a finish action, validating completion if configured.

        Returns:
            True if finish should proceed (validation passed or not configured),
            False if validation failed and the agent should continue working.
        """
        # Lightweight check: if code was edited, ensure tests were run recently
        if not getattr(action, "force_finish", False):
            if not await self._check_test_coverage(action):
                return False

        if await self._should_validate(action):
            if not await self._validate_and_handle(action):
                return False
        return True

    # ── internals ───────────────────────────────────────────────────

    async def _check_test_coverage(self, action: PlaybookFinishAction) -> bool:
        """Block finish once if code was edited but no tests were run recently.

        Scans the last 50 events for file-edit actions and test-run actions.
        If edits were made but no test run is found, emits a warning and
        resumes the agent so it can run tests first. Only blocks once per
        session to avoid infinite loops when tests are genuinely inapplicable.

        Returns True if ok to proceed, False if blocked.
        """
        if self._test_check_warned:
            return True  # Already warned once — let the agent finish
        controller = self._context.get_controller()
        history = getattr(controller.state, "history", [])
        if not history:
            return True

        # Only check the tail of history — no need to scan everything
        tail = list(history)[-50:]

        has_file_edits = False
        has_test_run = False

        for event in tail:
            action_type = getattr(event, "action", "")
            # Detect file edits
            if action_type in ("edit", "write"):
                has_file_edits = True
            # Also check by class name for FileEditAction events
            cls_name = type(event).__name__
            if cls_name == "FileEditAction":
                has_file_edits = True
            # Detect test runs — CmdRunAction with pytest/run_tests signature
            if cls_name == "CmdRunAction":
                cmd = getattr(event, "command", "")
                if "pytest" in cmd or "run_tests" in cmd or "unittest" in cmd:
                    has_test_run = True
            # Also detect via tool_call_metadata
            meta = getattr(event, "tool_call_metadata", None)
            if meta and getattr(meta, "function_name", "") == "run_tests":
                has_test_run = True

        if has_file_edits and not has_test_run:
            from backend.events.observation import ErrorObservation

            self._test_check_warned = True
            logger.info("Finish blocked: file edits detected without recent test run")
            warning = (
                "⚠️ FINISH BLOCKED: You made file edits but haven't run tests in this session.\n"
                "Please run tests with run_tests() to verify your changes before finishing.\n"
                "If tests are genuinely not applicable, use think() to explain why, then try finish again."
            )
            error_obs = ErrorObservation(
                content=warning,
                error_id="TESTS_NOT_RUN",
            )
            controller.event_stream.add_event(error_obs, EventSource.ENVIRONMENT)

            if controller.state.agent_state != AgentState.RUNNING:
                await controller.set_agent_state_to(AgentState.RUNNING)
            return False

        return True

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
