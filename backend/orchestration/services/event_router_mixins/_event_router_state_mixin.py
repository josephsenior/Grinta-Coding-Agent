"""State methods for EventRouterService.

State changes, plan tracking, and meta-cognition detection.

Extracted from backend/orchestration/services/event_router_service.py
to keep the parent module under the per-file LOC budget. All methods
rely on attributes/methods defined on EventRouterService; this mixin
is meant to be combined with that class via multiple inheritance.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from backend.core.schemas import AgentState
from backend.core.tasks.task_status import ACTIVE_TASK_STATUSES
from backend.ledger import EventSource
from backend.ledger.action import (
    Action,
    ChangeAgentStateAction,
)

if TYPE_CHECKING:
    from backend.orchestration.services.event_router_service import EventRouterService

logger = logging.getLogger(__name__)


class _EventRouterStateMixin(EventRouterService if TYPE_CHECKING else object):
    """Mixin class — see module docstring."""

    async def _handle_change_state_action(self, action: ChangeAgentStateAction) -> None:
        try:
            target_state = AgentState(action.agent_state)
        except ValueError:
            self._ctrl.log(
                'warning',
                "Received unknown agent state '%s', ignoring.",
                extra={'agent_state': action.agent_state},
            )
            return

        if (
            target_state == AgentState.AWAITING_USER_INPUT
            and action.source == EventSource.ENVIRONMENT
            and self._ctrl.get_agent_state() == AgentState.RUNNING
        ):
            self._ctrl.log(
                'debug',
                'Discarding stale startup ChangeAgentStateAction(AWAITING_USER_INPUT) '
                '— agent is already RUNNING',
            )
            return

        await self._ctrl.set_agent_state_to(target_state)

    async def _run_critics(self) -> None:
        """Retained lifecycle hook after finish; review critics were removed."""
        return

    def _task_tracker_has_unfinished_tasks(self) -> bool:
        state = getattr(self._ctrl, 'state', None)
        return self._plan_has_active_steps(getattr(state, 'plan', None))

    def _plan_has_active_steps(self, plan: object | None) -> bool:
        if plan is None:
            return False
        steps = getattr(plan, 'steps', None) or []
        return self._steps_have_active_status(steps)

    def _steps_have_active_status(self, steps: object) -> bool:
        if not isinstance(steps, list):
            return False
        for step in steps:
            if isinstance(step, dict):
                status = step.get('status')
                subtasks = step.get('subtasks')
            else:
                status = getattr(step, 'status', None)
                subtasks = getattr(step, 'subtasks', None)
            if str(status or '').strip().lower() in ACTIVE_TASK_STATUSES:
                return True
            if self._steps_have_active_status(subtasks or []):
                return True
        return False
