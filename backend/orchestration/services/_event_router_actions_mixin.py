"""Actions methods for EventRouterService.

Top-level event routing and action dispatch (route_event, _handle_action, message/task/finish/reject/meta handlers).

Extracted from backend/orchestration/services/event_router_service.py
to keep the parent module under the per-file LOC budget. All methods
rely on attributes/methods defined on EventRouterService; this mixin
is meant to be combined with that class via multiple inheritance.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from backend.core.agent_protocol import (
    mark_tracker_created,
    reset_terminal_cycle,
    tracker_created,
    tracker_terminal,
)
from backend.core.interaction_modes import (
    normalize_interaction_mode,
)
from backend.core.schemas import AgentState
from backend.ledger import EventSource
from backend.ledger.action import (
    Action,
    AgentRejectAction,
    ChangeAgentStateAction,
    MessageAction,
    PlaybookFinishAction,
    TaskTrackingAction,
)
from backend.ledger.action.agent import (
    DelegateTaskAction,
)
from backend.ledger.action.message import StreamingChunkAction
from backend.ledger.observation import (
    Observation,
)

if TYPE_CHECKING:
    from backend.ledger.event import Event
    from backend.orchestration.services.event_router_service import EventRouterService

logger = logging.getLogger(__name__)


class _EventRouterActionsMixin(EventRouterService if TYPE_CHECKING else object):
    """Mixin class — see module docstring."""

    async def route_event(self, event: Event) -> None:
        """Dispatch a single event to the appropriate handler.

        Hidden events are silently dropped.  Plugin hooks fire first.
        """
        if hasattr(event, 'hidden') and event.hidden:
            return

        # Plugin hook: event_emitted
        try:
            from backend.core.plugin import get_plugin_registry

            await get_plugin_registry().dispatch_event(event)
        except Exception as exc:
            self._ctrl.log(
                'warning',
                f'Plugin event_emitted hook failed for {type(event).__name__}: {exc}',
                extra={'msg_type': 'PLUGIN_EVENT_HOOK'},
            )

        # StreamingChunkAction events are transient display hints — they
        # must NOT be added to the history that the LLM sees on the next
        # step, otherwise the context window fills up with chunk noise.
        if not isinstance(event, StreamingChunkAction):
            self._ctrl.state_tracker.add_history(event)

        if isinstance(event, Action):
            await self._handle_action(event)
        elif isinstance(event, Observation):
            await self._handle_observation(event)

    async def _handle_action(self, action: Action) -> None:
        """Route an Action to its specific handler."""
        if isinstance(action, ChangeAgentStateAction):
            await self._handle_change_state_action(action)
            return

        for action_type, handler in (
            (MessageAction, self._handle_message_action),
            (PlaybookFinishAction, self._handle_finish_action),
            (AgentRejectAction, self._handle_reject_action),
            (TaskTrackingAction, self._handle_task_tracking_action),
            (DelegateTaskAction, self._handle_delegate_task_action),
        ):
            if isinstance(action, action_type):
                await handler(action)  # type: ignore[arg-type]
                return

        if self._is_meta_cognition_action(action):
            await self._handle_meta_cognition_action(action)

    async def _handle_task_tracking_action(self, action: TaskTrackingAction) -> None:
        """Handle task tracking action to update active plan."""
        from backend.orchestration.state.state import build_active_plan_from_payload

        try:
            current_plan = self._ctrl.state.plan
            current_title = current_plan.title if current_plan else 'Current Plan'
            self._ctrl.state.plan = build_active_plan_from_payload(
                action.task_list,
                title=current_title,
            )
            if action.command in {'create', 'update'} or action.task_list:
                mark_tracker_created(
                    self._ctrl.state,
                    source='EventRouterService.task_tracking',
                )
            if not tracker_terminal(self._ctrl.state):
                reset_terminal_cycle(self._ctrl.state)
            self._ctrl.log('info', f'Plan updated with {len(action.task_list)} steps.')
        except Exception as e:
            self._ctrl.log('error', f'Failed to update plan: {e}')

    async def _handle_finish_action(self, action: PlaybookFinishAction) -> None:
        """Handle agent finish action with completion validation."""
        if not await self._ctrl.task_validation_service.handle_finish(action):
            return
        self._ctrl.state.set_outputs(action.outputs, source='EventRouterService.finish')
        self._ctrl.state.extra_data.pop('active_run_mode', None)
        await self._ctrl.set_agent_state_to(AgentState.FINISHED)
        await self._ctrl.log_task_audit(status='success')
        await self._run_critics()

    async def _handle_reject_action(self, action: AgentRejectAction) -> None:
        """Handle agent reject action."""
        self._ctrl.state.set_outputs(action.outputs, source='EventRouterService.reject')
        await self._ctrl.set_agent_state_to(AgentState.REJECTED)

    async def _handle_message_action(self, action: MessageAction) -> None:
        """Handle message actions from users or agents."""
        if action.source == EventSource.USER:
            await self._handle_user_message(action)
        elif action.source == EventSource.AGENT:
            if bool(getattr(action, 'protocol_abandoned', False)):
                await self._ctrl.set_agent_state_to(AgentState.AWAITING_USER_INPUT)
                return
            if action.wait_for_response:
                if await self._intercept_text_tool_call_handoff(action):
                    return
                if self._task_tracker_has_unfinished_tasks():
                    if await self._intercept_protocol_message_handoff(action):
                        return
                await self._ctrl.set_agent_state_to(AgentState.AWAITING_USER_INPUT)

    async def _handle_meta_cognition_action(self, action: Action) -> None:
        """Handle meta-cognition actions (clarification, proposal, uncertainty, escalation).

        In FULL autonomy mode, the agent continues without pausing.
        In BALANCED or CONSERVATIVE mode, the agent pauses and waits for user input.

        Exceptions:
          - ``InformAction`` never pauses (it's a non-blocking status update).
          - In FULL autonomy, even explicit confirm requests do not pause; the
            safety validator remains the hard stop for forbidden operations.
        """
        from backend.ledger.action.agent import (
            ConfirmRequestAction,
            InformAction,
        )
        from backend.orchestration.autonomy import (
            AutonomyLevel,
            normalize_autonomy_level,
        )

        autonomy_ctrl = getattr(self._ctrl, 'autonomy_controller', None)
        autonomy_level = (
            getattr(autonomy_ctrl, 'autonomy_level', AutonomyLevel.BALANCED.value)
            if autonomy_ctrl
            else AutonomyLevel.BALANCED.value
        )
        autonomy_level = normalize_autonomy_level(autonomy_level)

        if (
            isinstance(action, ConfirmRequestAction)
            and autonomy_level == AutonomyLevel.FULL.value
        ):
            self._ctrl.log(
                'debug',
                'Meta-cognition confirm action ignored in full autonomy.',
                extra={'action_type': type(action).__name__},
            )
            return

        agent = getattr(self._ctrl, 'agent', None)
        config = getattr(agent, 'config', None)
        mode = normalize_interaction_mode(getattr(config, 'mode', 'agent'))

        if mode == 'agent' and tracker_created(self._ctrl.state):
            await self._ctrl.set_agent_state_to(AgentState.AWAITING_USER_INPUT)
            return

        if isinstance(action, InformAction):
            # Non-blocking outside committed Agent-mode task runs.
            self._ctrl.log(
                'debug',
                'Meta-cognition inform action (non-blocking).',
                extra={'action_type': type(action).__name__},
            )
            return

        should_pause = mode == 'plan' or autonomy_level != AutonomyLevel.FULL.value

        if should_pause:
            self._ctrl.log(
                'info',
                'Meta-cognition action requires user input, pausing agent.',
                extra={'action_type': type(action).__name__},
            )
            await self._ctrl.set_agent_state_to(AgentState.AWAITING_USER_INPUT)
