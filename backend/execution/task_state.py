"""Runtime integration for canonical task-state commands."""
from __future__ import annotations
from backend.ledger.observation import ErrorObservation, Observation
from backend.ledger.observation.task_state import TaskStateObservation

class TaskStateMixin:
    def _handle_task_state_action(self, action) -> Observation:
        try:
            from backend.task_state import TaskStateService
            state, content = TaskStateService().apply(action.command, action.arguments)
            return TaskStateObservation(content=content, command=action.command, revision=state.revision, state=state.to_dict())
        except (ValueError, TypeError) as exc:
            return ErrorObservation(f'Task state error: {exc}')
