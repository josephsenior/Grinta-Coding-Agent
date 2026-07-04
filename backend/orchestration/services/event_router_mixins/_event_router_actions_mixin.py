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

from backend.core.interaction_modes import (
    CHAT_MODE,
    PLAN_MODE,
    normalize_interaction_mode,
)
from backend.core.schemas import AgentState
from backend.ledger import EventSource
from backend.ledger.action import (
    Action,
    AgentRejectAction,
    ChangeAgentStateAction,
    MessageAction,
    TaskTrackingAction,
)
from backend.ledger.action.agent import (
    AgentThinkAction,
    DelegateTaskAction,
    SystemHintAction,
)
from backend.ledger.action.message import StreamingChunkAction
from backend.ledger.observation import (
    Observation,
)
from backend.orchestration.agent.agent_protocol import (
    mark_tracker_created,
    reset_terminal_cycle,
    tracker_terminal,
)

if TYPE_CHECKING:
    from backend.ledger.event import Event
    from backend.orchestration.services.event_router_service import EventRouterService

logger = logging.getLogger(__name__)


class _EventRouterActionsMixin(EventRouterService if TYPE_CHECKING else object):
    """Mixin class — see module docstring."""

    def _active_interaction_mode(self) -> str:
        state = getattr(self._ctrl, 'state', None)
        extra = getattr(state, 'extra_data', {}) or {}
        if isinstance(extra, dict):
            active_mode = extra.get('active_run_mode')
            if active_mode:
                return normalize_interaction_mode(active_mode)
        agent = getattr(self._ctrl, 'agent', None)
        config = getattr(agent, 'config', None)
        return normalize_interaction_mode(getattr(config, 'mode', 'agent'))

    def _is_plain_terminal_agent_message(self, action: MessageAction) -> bool:
        if action.source != EventSource.AGENT:
            return False
        if not str(getattr(action, 'content', '') or '').strip():
            return False
        if bool(getattr(action, 'wait_for_response', False)):
            return False
        if bool(getattr(action, 'transcript_only', False)):
            return False
        if bool(getattr(action, 'protocol_status', False)):
            return False
        if bool(getattr(action, 'suppress_cli', False)):
            return False
        return self._active_interaction_mode() in {CHAT_MODE, PLAN_MODE}

    @staticmethod
    def _record_agent_transcript(event: Event) -> None:
        from backend.core.logging.session_event_logger import emit_session_event

        event_id = getattr(event, 'id', None)
        eid = event_id if isinstance(event_id, int) else None

        if isinstance(event, StreamingChunkAction):
            if event.is_final:
                emit_session_event(
                    'AGENT_STEP',
                    {
                        'text': str(getattr(event, 'accumulated', '') or ''),
                        'thinking': str(
                            getattr(event, 'thinking_accumulated', '') or ''
                        ),
                        'event_id': eid,
                        'stream_final': True,
                        'suppress_live_response': bool(
                            getattr(event, 'suppress_live_response', False)
                        ),
                    },
                )
            return

        if isinstance(event, (AgentThinkAction, SystemHintAction)):
            thought = str(getattr(event, 'thought', '') or '')
            if thought.strip():
                emit_session_event(
                    'AGENT_THINK',
                    {'thought': thought, 'event_id': eid},
                )
            return

        if isinstance(event, MessageAction):
            content = str(getattr(event, 'content', '') or '')
            if not content.strip():
                return
            if event.source == EventSource.USER:
                emit_session_event(
                    'USER_TURN',
                    {'text': content, 'event_id': eid},
                )
            elif event.source == EventSource.AGENT:
                emit_session_event(
                    'AGENT_STEP',
                    {
                        'text': content,
                        'thinking': str(getattr(event, 'thought', '') or ''),
                        'event_id': eid,
                        'final_response': bool(getattr(event, 'final_response', False)),
                        'tool_step': bool(getattr(event, 'transcript_only', False)),
                    },
                )

    async def route_event(self, event: Event) -> None:
        """Dispatch a single event to the appropriate handler.

        Hidden events are silently dropped.  Plugin hooks fire first.
        """
        if hasattr(event, 'hidden') and event.hidden:
            return

        self._record_agent_transcript(event)

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

    async def _handle_reject_action(self, action: AgentRejectAction) -> None:
        """Handle agent reject action."""
        self._ctrl.state.set_outputs(action.outputs, source='EventRouterService.reject')
        await self._ctrl.set_agent_state_to(AgentState.REJECTED)

    async def _handle_message_action(self, action: MessageAction) -> None:
        """Handle message actions from users or agents."""
        if action.source == EventSource.USER:
            await self._handle_user_message(action)
        elif action.source == EventSource.AGENT:
            if action.wait_for_response:
                if await self._intercept_text_tool_call_handoff(action):
                    return
                await self._ctrl.set_agent_state_to(AgentState.AWAITING_USER_INPUT)
                return
            is_final_response = bool(
                getattr(action, 'final_response', False)
            ) or self._is_plain_terminal_agent_message(action)
            if is_final_response:
                action.final_response = True
                # Optional LLM-judge quality check; emits a warning on
                # failure but never blocks the transition.
                await self._ctrl.task_validation_service.validate_completion_quality(
                    action
                )
                content = str(getattr(action, 'content', '') or '').strip()
                self._ctrl.state.set_outputs(
                    {
                        'status': 'completed',
                        'response': content,
                        'summary': content,
                    },
                    source='EventRouterService.final_response',
                )
                self._ctrl.state.extra_data.pop('active_run_mode', None)
                try:
                    from backend.engine.tools.session_lessons import (
                        persist_finish_lessons,
                    )

                    persist_finish_lessons(
                        summary=content,
                        session_id=self._ctrl.id,
                    )
                except Exception:
                    pass
                await self._ctrl.set_agent_state_to(AgentState.FINISHED)
                await self._ctrl.log_task_audit(status='success')

    async def _handle_meta_cognition_action(self, action: Action) -> None:
        """Handle meta-cognition actions (clarification, proposal, uncertainty, escalation).

        In FULL autonomy mode, the agent continues without pausing.
        In BALANCED or CONSERVATIVE mode, the agent pauses and waits for user input.

        Exceptions:
          - ``InformAction`` never pauses (it's a non-blocking status update).
          - In FULL autonomy, even explicit confirm requests do not pause; the
            safety validator remains the hard stop for forbidden operations.
        """
        self._ctrl.log(
            'debug',
            'Ignoring legacy meta-cognition action; ask_user is the model-facing communication tool.',
            extra={'action_type': type(action).__name__},
        )
