"""Optional LLM-judge quality check for plain-text final responses.

This service is intentionally minimal. The historical structural middleware
that gated the state transition on plan completeness, summary presence,
and skipped/blocked item reporting has been removed: a plain-text final
response from the agent is its explicit decision to end the run, and
overriding that decision leaves the agent stuck in ``RUNNING`` with no
next step scheduled.

The LLM-based completion validator (``task_validator``) is retained as an
*opt-in* quality signal. When wired and enabled, its verdict is emitted as
a warning observation; it does not block the transition to
``AgentState.FINISHED``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.core.logging.logger import app_logger as logger  # noqa: E402
from backend.ledger import EventSource  # noqa: E402
from backend.ledger.action import MessageAction  # noqa: E402

if TYPE_CHECKING:
    from backend.orchestration.services.orchestration_context import (
        OrchestrationContext,
    )


class TaskValidationService:
    """Runs the optional LLM-judge quality gate on a final-response action.

    The method never returns ``False``: a failing validator emits a
    warning observation for the agent's transcript but does not block the
    transition to ``AgentState.FINISHED``. Callers should not branch on
    the return value.
    """

    def __init__(self, context: OrchestrationContext) -> None:
        self._context = context

    async def validate_completion_quality(self, action: MessageAction) -> None:
        """Emit a warning observation if the optional validator rejects the action."""
        controller = self._context.get_controller()
        validator = getattr(controller, 'task_validator', None)
        if validator is None:
            return

        agent = getattr(controller, 'agent', None)
        config = getattr(agent, 'config', None) if agent else None
        enabled_raw = getattr(config, 'enable_completion_validation', False)
        enabled = isinstance(enabled_raw, bool) and enabled_raw
        if not enabled:
            return

        task = controller._get_initial_task()
        if task is None:
            return

        try:
            validation = await validator.validate_completion(task, controller.state)
        except Exception as exc:  # pragma: no cover - defensive log
            logger.warning('Completion validator raised; ignoring: %s', exc)
            return

        if validation.passed:
            logger.info(
                'Completion validator passed for final response: %s', validation.reason
            )
            return

        logger.info(
            'Completion validator flagged final response (%s); emitting warning only.',
            validation.reason,
        )
        feedback = self._build_feedback(validation)
        await self._emit_warning(feedback, action)

    @staticmethod
    def _build_feedback(validation: Any) -> str:
        """Build a human-readable warning message from a validator result."""
        feedback = (
            f'Completion validator note: {validation.reason}\n\n'
            f'Confidence: {validation.confidence:.1%}\n'
        )

        if getattr(validation, 'missing_items', None):
            feedback += '\nPossible gaps:\n' + '\n'.join(
                f'- {item}' for item in validation.missing_items
            )

        if getattr(validation, 'suggestions', None):
            feedback += '\n\nSuggestions:\n' + '\n'.join(
                f'- {sug}' for sug in validation.suggestions
            )

        return feedback

    async def _emit_warning(self, message: str, action: MessageAction) -> None:
        from backend.ledger.observation import ErrorObservation
        from backend.ledger.observation_cause import attach_observation_cause

        controller = self._context.get_controller()
        warning = ErrorObservation(
            content=message,
            error_id='COMPLETION_VALIDATOR_NOTE',
        )
        attach_observation_cause(
            warning,
            action,
            context='task_validation_service.quality_warning',
        )
        controller.event_stream.add_event(warning, EventSource.ENVIRONMENT)
