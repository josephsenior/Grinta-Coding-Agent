"""Service for validating task completion before allowing agent finish."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.core.logger import app_logger as logger  # noqa: E402
from backend.core.schemas import AgentState  # noqa: E402
from backend.core.task_status import ACTIVE_TASK_STATUSES
from backend.ledger import EventSource  # noqa: E402
from backend.ledger.action.agent import PlaybookFinishAction  # noqa: E402

if TYPE_CHECKING:
    from backend.orchestration.services.orchestration_context import (
        OrchestrationContext,
    )


def _step_field(step: Any, name: str, default: Any) -> Any:
    if isinstance(step, dict):
        return step.get(name, default)
    return getattr(step, name, default)


def _step_identity(step: Any) -> tuple[str, str, str, list[Any]]:
    status = str(_step_field(step, 'status', '') or '').strip().lower()
    step_id = str(_step_field(step, 'id', '?') or '?')
    description = str(
        _step_field(step, 'description', 'Untitled step') or 'Untitled step'
    )
    subtasks = _step_field(step, 'subtasks', None) or []
    return step_id, description, status, subtasks


class TaskValidationService:
    """Validates agent task completion using a pluggable validator.

    Extracted from SessionOrchestrator to keep the controller focused on
    orchestration while this service owns the validation decision logic.
    """

    def __init__(self, context: OrchestrationContext) -> None:
        self._context = context

    async def handle_finish(self, action: PlaybookFinishAction) -> bool:
        """Handle a finish action, validating completion if configured.

        Returns:
            True if finish should proceed (validation passed or not configured),
            False if validation failed and the agent should continue working.
        """
        # Save any lessons learned before finishing
        await self._save_lessons_learned(action)

        if not await self._ensure_active_plan_is_terminal(action):
            return False

        if not await self._ensure_completion_validator_available(action):
            return False

        if await self._should_validate(action):
            if not await self._validate_and_handle(action):
                return False
        return True

    async def _ensure_active_plan_is_terminal(
        self, action: PlaybookFinishAction
    ) -> bool:
        """Block finish when the visible active plan still has tasks in progress."""
        controller = self._context.get_controller()
        plan = getattr(controller.state, 'plan', None)
        used_task_tracker = self._session_used_task_tracker()
        if plan is None and not used_task_tracker:
            return True

        active_steps = self._collect_non_terminal_steps(getattr(plan, 'steps', []))
        if plan is not None or used_task_tracker:
            active_steps = self._dedupe_active_steps(
                active_steps + self._load_persisted_non_terminal_steps()
            )
        if not active_steps:
            return True

        bullets = '\n'.join(
            f'- {step_id}: {description} [{status}]'
            for step_id, description, status in active_steps[:5]
        )
        more = ''
        if len(active_steps) > 5:
            more = f'\n- ... and {len(active_steps) - 5} more plan step(s)'

        return await self._emit_finish_block(
            '⚠️ FINISH BLOCKED: The task plan still has active steps. '
            'You must ensure all tasks are marked `done` or another terminal state (`skipped` or `blocked`) '
            'before calling the finish tool.\n\n'
            f'Active steps:\n{bullets}{more}',
            error_id='TASK_TRACKER_INCOMPLETE',
            cause_action=action,
        )

    def _session_used_task_tracker(self) -> bool:
        """True when the current session has used task tracking at least once."""
        history = getattr(self._context.get_controller().state, 'history', None)
        if not isinstance(history, list):
            return False

        from backend.ledger.action import TaskTrackingAction
        from backend.ledger.observation import TaskTrackingObservation

        return any(
            isinstance(event, (TaskTrackingAction, TaskTrackingObservation))
            for event in history
        )

    def _load_persisted_non_terminal_steps(self) -> list[tuple[str, str, str]]:
        """Load active steps from the persisted workspace plan when available."""
        controller = self._context.get_controller()
        config = getattr(controller, 'config', None)
        project_root = getattr(config, 'project_root', None)
        if not isinstance(project_root, str) or not project_root.strip():
            return []

        try:
            from backend.engine.tools.task_tracker import TaskTracker

            persisted_steps = TaskTracker(project_root.strip()).load_from_file()
        except Exception as exc:
            logger.debug('Could not load persisted active plan for finish validation: %s', exc)
            return []

        return self._collect_non_terminal_steps(persisted_steps)

    @staticmethod
    def _dedupe_active_steps(
        steps: list[tuple[str, str, str]]
    ) -> list[tuple[str, str, str]]:
        """Return stable unique active-step tuples preserving first-seen order."""
        unique: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for step in steps:
            if step in seen:
                continue
            seen.add(step)
            unique.append(step)
        return unique

    def _collect_non_terminal_steps(
        self, steps: list[Any]
    ) -> list[tuple[str, str, str]]:
        """Return visible plan steps that are still todo or doing."""
        active_steps: list[tuple[str, str, str]] = []
        for step in steps or []:
            step_id, description, status, subtasks = _step_identity(step)
            if status in ACTIVE_TASK_STATUSES:
                active_steps.append(
                    (
                        step_id,
                        description,
                        status,
                    )
                )
            active_steps.extend(self._collect_non_terminal_steps(subtasks))
        return active_steps

    async def _save_lessons_learned(self, action: PlaybookFinishAction) -> None:
        """Persist lessons learned to a repository-level memory file."""
        outputs = getattr(action, 'outputs', {})
        if not outputs or not isinstance(outputs, dict):
            return

        lesson = outputs.get('lessons_learned')
        if not lesson or not str(lesson).strip():
            return

        from datetime import datetime
        from pathlib import Path

        from backend.core.workspace_resolution import workspace_agent_state_dir

        file_store = self._context.get_controller().config.file_store
        project_root = Path(file_store.root) if file_store else None
        memories_path = workspace_agent_state_dir(project_root) / 'lessons.md'

        try:
            memories_path.parent.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
            initial_task = self._context.get_controller()._get_initial_task()
            summary = initial_task.description[:100] if initial_task else 'Task'

            entry = f'\n## {timestamp} — {summary}\n{lesson}\n'

            with open(memories_path, 'a', encoding='utf-8') as f:  # noqa: ASYNC230
                f.write(entry)

            logger.info('Saved lessons learned to %s', memories_path)
        except Exception as e:
            logger.warning('Failed to save lessons learned: %s', e)

    async def _emit_finish_block(
        self,
        message: str,
        error_id: str,
        *,
        cause_action: Any | None = None,
    ) -> bool:
        from backend.ledger.observation import ErrorObservation
        from backend.ledger.observation_cause import attach_observation_cause

        controller = self._context.get_controller()
        error_obs = ErrorObservation(content=message, error_id=error_id, agent_only=True)
        attach_observation_cause(
            error_obs,
            cause_action,
            context='task_validation_service.finish_block',
        )
        controller.event_stream.add_event(error_obs, EventSource.ENVIRONMENT)

        if controller.state.agent_state != AgentState.RUNNING:
            await controller.set_agent_state_to(AgentState.RUNNING)
        return False

    async def _ensure_completion_validator_available(
        self, action: PlaybookFinishAction
    ) -> bool:
        """Fail closed when completion validation is enabled but validator is missing."""
        if getattr(action, 'force_finish', False):
            return True

        controller = self._context.get_controller()
        validator = getattr(controller, 'task_validator', None)
        if validator is not None:
            return True

        agent = getattr(controller, 'agent', None)
        config = getattr(agent, 'config', None) if agent else None
        enabled_raw = getattr(config, 'enable_completion_validation', False)
        completion_validation_enabled = isinstance(enabled_raw, bool) and enabled_raw
        if not completion_validation_enabled:
            return True

        logger.warning(
            'Finish blocked: completion validation is enabled but no validator is configured'
        )
        return await self._emit_finish_block(
            '⚠️ FINISH BLOCKED: Completion validation is enabled but the validator is unavailable. '
            'Please continue working or retry once validation is restored.',
            error_id='TASK_VALIDATOR_UNAVAILABLE',
            cause_action=action,
        )

    async def _should_validate(self, action: PlaybookFinishAction) -> bool:
        """Check if task completion should be validated."""
        controller = self._context.get_controller()
        validator = getattr(controller, 'task_validator', None)
        return bool(validator) and not getattr(action, 'force_finish', False)

    async def _validate_and_handle(self, action: PlaybookFinishAction) -> bool:
        """Run the validator and handle the result.

        Returns True if passed, False if failed.
        """
        controller = self._context.get_controller()
        task = controller._get_initial_task()
        if not task:
            return True

        validator = getattr(controller, 'task_validator', None)
        if validator is None:
            return True

        logger.info('Validating task completion before finishing...')
        validation = await validator.validate_completion(task, controller.state)

        if not validation.passed:
            await self._handle_failure(action, validation)
            return False

        logger.info('Task completion validation passed: %s', validation.reason)
        return True

    async def _handle_failure(
        self, action: PlaybookFinishAction, validation: Any
    ) -> None:
        """Emit an error observation and resume the agent on validation failure."""
        from backend.ledger.observation import ErrorObservation
        from backend.ledger.observation_cause import attach_observation_cause

        controller = self._context.get_controller()
        logger.warning('Task completion validation failed: %s', validation.reason)

        feedback = self._build_feedback(validation)
        error_obs = ErrorObservation(
            content=feedback,
            error_id='TASK_VALIDATION_FAILED',
        )
        attach_observation_cause(
            error_obs,
            action,
            context='task_validation_service.validation_failed',
        )
        controller.event_stream.add_event(error_obs, EventSource.ENVIRONMENT)

        if controller.state.agent_state != AgentState.RUNNING:
            await controller.set_agent_state_to(AgentState.RUNNING)

    @staticmethod
    def _build_feedback(validation: Any) -> str:
        """Build a human-readable feedback message from a validation result."""
        feedback = f'TASK NOT COMPLETE: {validation.reason}\n\nConfidence: {validation.confidence:.1%}\n'

        if validation.missing_items:
            feedback += '\nMissing items:\n' + '\n'.join(
                f'- {item}' for item in validation.missing_items
            )

        if validation.suggestions:
            feedback += '\n\nSuggestions:\n' + '\n'.join(
                f'- {sug}' for sug in validation.suggestions
            )

        feedback += '\n\nPlease continue working to complete the task.'
        return feedback
