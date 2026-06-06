"""User_message methods for EventRouterService.

User message routing: recall type selection, pending recall, protocol handoffs.

Extracted from backend/orchestration/services/event_router_service.py
to keep the parent module under the per-file LOC budget. All methods
rely on attributes/methods defined on EventRouterService; this mixin
is meant to be combined with that class via multiple inheritance.
"""

from __future__ import annotations

import logging
import os as _os
from typing import TYPE_CHECKING

from backend.core.interaction_modes import (
    CHAT_MODE_NAMES,
    normalize_interaction_mode,
)
from backend.core.schemas import AgentState
from backend.ledger import EventSource, RecallType
from backend.ledger.action import (
    MessageAction,
)
from backend.ledger.action.agent import (
    RecallAction,
)
from backend.ledger.observation import (
    ErrorObservation,
)
from backend.ledger.observation_cause import attach_observation_cause
from backend.orchestration.services.event_router_mixins._event_router_delegate_helpers import (
    _looks_like_text_tool_call_handoff,
)

if TYPE_CHECKING:
    from backend.orchestration.services.event_router_service import EventRouterService

logger = logging.getLogger(__name__)


class _EventRouterUserMessageMixin(EventRouterService if TYPE_CHECKING else object):
    """Mixin class — see module docstring."""

    def _first_user_message(self) -> MessageAction | None:
        return next(
            (
                event
                for event in self._ctrl.event_stream.search_events(
                    start_id=self._ctrl.state.start_id
                )
                if isinstance(event, MessageAction) and event.source == EventSource.USER
            ),
            None,
        )

    def _recall_type_for_user_message(self, action: MessageAction) -> RecallType:
        first_user_message = self._first_user_message()
        is_first = action.id == first_user_message.id if first_user_message else False
        return RecallType.WORKSPACE_CONTEXT if is_first else RecallType.KNOWLEDGE

    def _set_pending_recall(
        self, recall_action: RecallAction, recall_type: RecallType
    ) -> None:
        pending_service = getattr(self._ctrl, 'pending_action_service', None)
        if recall_type == RecallType.WORKSPACE_CONTEXT:
            if pending_service is not None:
                pending_service.set(recall_action)
                return

            action_service = getattr(self._ctrl, 'action_service', None)
            if action_service is not None:
                action_service.set_pending_action(recall_action)
            return

        if pending_service is not None:
            pending_service.set(None)

        cb_svc = getattr(self._ctrl, 'circuit_breaker_service', None)
        if cb_svc is not None:
            cb_svc.reset_for_new_turn()

        state = getattr(self._ctrl, 'state', None)
        if state is not None:
            state.extra_data.pop('__step_guard_warning_trip_counts', None)

    async def _ensure_running_for_user_message(self) -> None:
        if self._ctrl.get_agent_state() != AgentState.RUNNING:
            await self._ctrl.set_agent_state_to(AgentState.RUNNING)

    async def _handle_user_message(self, action: MessageAction) -> None:
        """Handle user message: log, create recall, set pending, start agent."""
        log_level = 'info' if _os.getenv('LOG_ALL_EVENTS') in ('true', '1') else 'debug'
        self._ctrl.log(
            log_level,
            str(action),
            extra={'msg_type': 'ACTION', 'event_source': EventSource.USER},
        )
        recall_type = self._recall_type_for_user_message(action)
        recall_action = RecallAction(query=action.content, recall_type=recall_type)
        agent = getattr(self._ctrl, 'agent', None)
        config = getattr(agent, 'config', None)
        mode = normalize_interaction_mode(getattr(config, 'mode', 'agent'))
        if mode in CHAT_MODE_NAMES:
            self._ctrl.state.extra_data.pop('active_run_mode', None)
        else:
            self._ctrl.state.set_extra(
                'active_run_mode',
                mode,
                source='EventRouterService.user_message',
            )
        reset_recovery = getattr(
            getattr(self._ctrl, 'action_execution', None),
            'reset_liveness_recovery_counters',
            None,
        )
        if callable(reset_recovery):
            reset_recovery()

        # Assign stream id before pending so pending always references a stable id.
        self._ctrl.event_stream.add_event(recall_action, EventSource.USER)
        self._set_pending_recall(recall_action, recall_type)
        await self._ensure_running_for_user_message()

    async def _intercept_text_tool_call_handoff(self, action: MessageAction) -> bool:
        content = str(getattr(action, 'content', '') or '')
        if not _looks_like_text_tool_call_handoff(content):
            return False

        guidance = (
            'The previous response contained raw tool-call transport text instead '
            'of a usable Grinta tool action. Re-emit exactly one valid tool call '
            'with structured arguments.'
        )
        await self._reject_agent_message_handoff(
            action,
            guidance,
            source='EventRouterService._intercept_text_tool_call_handoff',
            error_id='TEXT_TOOL_CALL_FORMAT_INCOMPLETE',
        )
        return True

    async def _reject_agent_message_handoff(
        self,
        action: MessageAction,
        guidance: str,
        *,
        source: str,
        error_id: str,
    ) -> None:
        state = getattr(self._ctrl, 'state', None)
        if state is not None and hasattr(state, 'set_planning_directive'):
            state.set_planning_directive(
                guidance,
                source=source,
            )
        else:
            observation = ErrorObservation(
                content=guidance,
                error_id=error_id,
            )
            attach_observation_cause(
                observation,
                action,
                context=source,
            )
            self._ctrl.event_stream.add_event(observation, EventSource.ENVIRONMENT)
        action.suppress_cli = True
        action.wait_for_response = False
