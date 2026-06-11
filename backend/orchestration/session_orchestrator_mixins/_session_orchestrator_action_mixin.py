from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from backend.core.logger import app_logger as logger
from backend.ledger import EventSource
from backend.ledger.action import (
    Action,
    MessageAction,
    SystemMessageAction,
)
from backend.orchestration.tool_pipeline import ToolInvocationContext

TRAFFIC_CONTROL_REMINDER = (
    "Please click on resume button if you'd like to continue, or start a new task."
)
ERROR_ACTION_NOT_EXECUTED_STOPPED_ID = 'AGENT_ERROR$ERROR_ACTION_NOT_EXECUTED_STOPPED'
ERROR_ACTION_NOT_EXECUTED_ERROR_ID = 'AGENT_ERROR$ERROR_ACTION_NOT_EXECUTED_ERROR'
ERROR_ACTION_NOT_EXECUTED_STOPPED = 'Run cancelled (Stop or Ctrl+C) before this tool finished — the action was not executed.'
ERROR_ACTION_NOT_EXECUTED_ERROR = (
    'Runtime error or restart prevented this action from completing (unlike cancelling with '
    'Stop or Ctrl+C). The execution environment may have crashed or been recycled. '
    'Any previously established system state, dependencies, or environment variables '
    'may have been lost. Consider using /resume to restore a crashed session.'
)

PARALLEL_TOOL_BATCH_RETRIES = 1
PARALLEL_TOOL_BATCH_BACKOFF_SECONDS = 0.25


def _mark_retry_serial_after_parallel_failure(action: Action) -> None:
    cast(Any, action)._retry_serial_after_parallel_failure = True


def _invoke_zero_arg_callback(callback: Callable[[], object]) -> object:
    return callback()


if TYPE_CHECKING:
    from backend.ledger.action import Action, MessageAction, SystemMessageAction
    from backend.ledger.event import EventSource
    from backend.orchestration.tool_pipeline import ToolInvocationContext

"""_SessionOrchestratorActionMixin mixin for SessionOrchestrator.

Pure code motion: extracted from
``backend/orchestration/session_orchestrator.py`` to break the file past the
40 KB cap. Methods here are bound to ``_SessionOrchestratorActionMixin`` and mixed into
``SessionOrchestrator`` via its MRO.
"""


class _SessionOrchestratorActionMixin:
    """Mixin: action context registration/binding/cleanup, system messages, log."""

    def _sync_budget_flag_with_metrics(self) -> None:
        """Keep the budget control flag aligned with accumulated metrics."""
        tracker = getattr(self, 'state_tracker', None)

        if tracker and hasattr(tracker, 'sync_budget_flag_with_metrics'):
            tracker.sync_budget_flag_with_metrics()

    def _register_action_context(
        self, action: Action, ctx: ToolInvocationContext
    ) -> None:
        """Register an invocation context before execution."""
        if hasattr(self, '_action_contexts_by_object'):
            self._action_contexts_by_object[id(action)] = ctx

    def _bind_action_context(self, action: Action, ctx: ToolInvocationContext) -> None:
        """Bind a context to an action's event ID after emission."""
        if not hasattr(self, '_action_contexts_by_event_id'):
            return

        ctx.action_id = action.id

        if ctx.action_id is not None:
            self._action_contexts_by_event_id[ctx.action_id] = ctx

        if hasattr(self, '_action_contexts_by_object'):
            with contextlib.suppress(KeyError):
                self._action_contexts_by_object.pop(id(action))

    def _cleanup_action_context(
        self,
        ctx: ToolInvocationContext,
        *,
        action: Action | None = None,
    ) -> None:
        """Remove context bookkeeping entries."""
        if hasattr(self, '_action_contexts_by_object'):
            if action is not None:
                with contextlib.suppress(KeyError):
                    self._action_contexts_by_object.pop(id(action))

            else:
                keys_to_remove = [
                    key
                    for key, value in self._action_contexts_by_object.items()
                    if value is ctx
                ]

                for key in keys_to_remove:
                    with contextlib.suppress(KeyError):
                        self._action_contexts_by_object.pop(key)

        if hasattr(self, '_action_contexts_by_event_id') and ctx.action_id is not None:
            with contextlib.suppress(KeyError):
                self._action_contexts_by_event_id.pop(ctx.action_id)

    def _add_system_message(self) -> None:
        """Add system message to event stream if not already present.

        Checks if a system message has already been added for this agent session.

        If not, retrieves the agent's system message and adds it to the event stream.

        """
        for event in self.event_stream.search_events(start_id=self.state.start_id):
            if isinstance(event, MessageAction) and event.source == EventSource.USER:
                return

            if isinstance(event, SystemMessageAction):
                return

        system_message = self.agent.get_system_message()

        if system_message and system_message.content:
            preview = (
                f'{system_message.content[:50]}...'
                if len(system_message.content) > 50
                else system_message.content
            )

            logger.debug('System message: %s', preview)

            self.event_stream.add_event(system_message, EventSource.AGENT)

    def log(self, level: str, message: str, extra: dict | None = None) -> None:
        """Logs a message to the agent controller's logger.

        Args:
            level (str): The logging level to use (e.g., 'info', 'debug', 'error').

            message (str): The message to log.

            extra (dict | None, optional): Additional fields to log. Includes session_id by default.



        """
        message = f'[Agent Controller {self.id}] {message}'

        if extra is None:
            extra = {}

        extra_merged = {'session_id': self.id, **extra}

        getattr(logger, level)(message, extra=extra_merged, stacklevel=2)
