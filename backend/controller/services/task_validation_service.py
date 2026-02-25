"""Service for validating task completion before allowing agent finish."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any


@dataclass
class _TestCoverageResult:
    has_file_edits: bool
    has_test_run: bool
    has_passing_test_run: bool

from backend.core.logger import forge_logger as logger
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
        # Save any lessons learned before finishing
        await self._save_lessons_learned(action)

        # Lightweight check: if code was edited, ensure tests were run recently
        if not getattr(action, "force_finish", False):
            if not await self._check_test_coverage(action):
                return False

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
        project_root = self._context.get_controller().config.file_store.root_dir if self._context.get_controller().config.file_store else "."
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

    # ── internals ───────────────────────────────────────────────────

    async def _check_test_coverage(self, action: PlaybookFinishAction) -> bool:
        """Block finish when code edits exist without a successful test run.

        Returns True if ok to proceed, False if blocked.
        """
        if self._has_explicit_test_skip(action):
            return True

        controller = self._context.get_controller()
        history = getattr(controller.state, "history", [])
        if not isinstance(history, (list, tuple)) or not history:
            return True

        tail = list(history)[-80:]
        coverage = self._analyze_test_coverage(tail)

        if coverage.has_file_edits and not coverage.has_test_run:
            logger.info("Finish blocked: file edits detected without recent test run")
            return await self._emit_finish_block(
                "⚠️ FINISH BLOCKED: You made file edits but haven't run tests in this session.\n"
                "Please run tests with run_tests() to verify your changes before finishing.\n"
                "If tests are genuinely not applicable, provide outputs.tests_not_applicable=true and "
                "outputs.tests_not_applicable_reason, then try finish again.",
                error_id="TESTS_NOT_RUN",
            )

        if coverage.has_file_edits and coverage.has_test_run and not coverage.has_passing_test_run:
            logger.info("Finish blocked: tests were run but no passing result detected")
            return await self._emit_finish_block(
                "⚠️ FINISH BLOCKED: Tests were run but no successful test result was detected.\n"
                "Fix failing tests (or run relevant tests successfully) before finishing.",
                error_id="TESTS_NOT_PASSING",
            )

        return True

    def _analyze_test_coverage(self, tail: list) -> _TestCoverageResult:
        """Analyze recent history for file edits and test execution."""
        from backend.events.action import CmdRunAction, FileEditAction, FileWriteAction
        from backend.events.observation import CmdOutputObservation

        has_file_edits = False
        has_test_run = False
        has_passing_test_run = False

        for idx, event in enumerate(tail):
            if isinstance(event, (FileEditAction, FileWriteAction)):
                if getattr(event, "command", None) != "view":
                    has_file_edits = True

            if isinstance(event, CmdRunAction):
                if self._is_test_command(event):
                    has_test_run = True
                    has_passing_test_run |= self._has_passing_output_after(tail, idx)
                if self._is_run_tests_tool(event):
                    has_test_run = True

        return _TestCoverageResult(has_file_edits, has_test_run, has_passing_test_run)

    def _is_test_command(self, event: Any) -> bool:
        """Return True if the command appears to run tests (pytest, run_tests, unittest)."""
        cmd = (getattr(event, "command", "") or "").lower()
        return any(tok in cmd for tok in ("pytest", "run_tests", "unittest"))

    def _has_passing_output_after(self, tail: list, idx: int) -> bool:
        """Return True if the next CmdOutputObservation (within 5 events) has exit_code 0."""
        from backend.events.observation import CmdOutputObservation

        for next_event in tail[idx + 1 : idx + 6]:
            if isinstance(next_event, CmdOutputObservation):
                return getattr(next_event, "exit_code", None) == 0
        return False

    def _is_run_tests_tool(self, event: Any) -> bool:
        """Return True if event's tool_call_metadata indicates run_tests was invoked."""
        meta = getattr(event, "tool_call_metadata", None)
        return bool(meta and getattr(meta, "function_name", "") == "run_tests")

    def _has_explicit_test_skip(self, action: PlaybookFinishAction) -> bool:
        outputs = getattr(action, "outputs", {})
        if not isinstance(outputs, dict):
            return False
        if not outputs.get("tests_not_applicable"):
            return False
        reason = str(outputs.get("tests_not_applicable_reason", "")).strip()
        return len(reason) >= 12

    async def _emit_finish_block(self, message: str, error_id: str) -> bool:
        from backend.events.observation import ErrorObservation

        controller = self._context.get_controller()
        error_obs = ErrorObservation(content=message, error_id=error_id)
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
