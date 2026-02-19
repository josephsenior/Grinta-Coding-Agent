"""Event routing service for AgentController.

Routes incoming events from the EventStream to appropriate handlers. Centralizes
all event dispatch logic that was previously inline in AgentController._on_event.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from backend.core.schemas import AgentState
from backend.events import EventSource, RecallType
from backend.events.action import (
    Action,
    AgentRejectAction,
    ChangeAgentStateAction,
    MessageAction,
    PlaybookFinishAction,
    TaskTrackingAction,
)
from backend.events.action.agent import RecallAction
from backend.events.observation import (
    Observation,
)

if TYPE_CHECKING:
    from backend.controller.agent_controller import AgentController
    from backend.events.event import Event


class EventRouterService:
    """Routes events to the correct handler on AgentController.

    Separates the *what-to-do-with-events* concern from the controller's
    step-execution and lifecycle management.
    """

    def __init__(self, controller: AgentController) -> None:
        self._ctrl = controller

    # ── public entry point ────────────────────────────────────────────

    async def route_event(self, event: Event) -> None:
        """Dispatch a single event to the appropriate handler.

        Hidden events are silently dropped.  Plugin hooks fire first.
        """
        if hasattr(event, "hidden") and event.hidden:
            return

        # Plugin hook: event_emitted
        try:
            from backend.core.plugin import get_plugin_registry

            await get_plugin_registry().dispatch_event(event)
        except Exception:
            pass

        self._ctrl.state_tracker.add_history(event)

        if isinstance(event, Action):
            await self._handle_action(event)
        elif isinstance(event, Observation):
            await self._handle_observation(event)

    # ── action dispatch ───────────────────────────────────────────────

    async def _handle_action(self, action: Action) -> None:
        """Route an Action to its specific handler."""
        if isinstance(action, ChangeAgentStateAction):
            try:
                target_state = AgentState(action.agent_state)
            except ValueError:
                self._ctrl.log(
                    "warning",
                    "Received unknown agent state '%s', ignoring.",
                    extra={"agent_state": action.agent_state},
                )
            else:
                await self._ctrl.set_agent_state_to(target_state)
        elif isinstance(action, MessageAction):
            await self._handle_message_action(action)
        elif isinstance(action, PlaybookFinishAction):
            await self._handle_finish_action(action)
        elif isinstance(action, AgentRejectAction):
            await self._handle_reject_action(action)
        elif isinstance(action, TaskTrackingAction):
            await self._handle_task_tracking_action(action)

    async def _handle_task_tracking_action(self, action: TaskTrackingAction) -> None:
        """Handle task tracking action to update active plan."""
        from backend.controller.state.state import ActivePlan, PlanStep

        try:
            # Recursive helper to build steps
            def _build_step(d: dict) -> PlanStep:
                return PlanStep(
                    id=d.get("id", ""),
                    description=d.get("description", d.get("title", "")),
                    status=d.get("status", "pending"),
                    result=d.get("result", d.get("notes")),
                    tags=d.get("tags", []),
                    subtasks=[_build_step(s) for s in d.get("subtasks", [])],
                )

            current_plan = self._ctrl.state.plan
            current_title = current_plan.title if current_plan else "Current Plan"

            steps = [_build_step(t) for t in action.task_list]
            self._ctrl.state.plan = ActivePlan(
                steps=steps,
                title=current_title,
            )
            self._ctrl.log("info", f"Plan updated with {len(steps)} steps.")
        except Exception as e:
            self._ctrl.log("error", f"Failed to update plan: {e}")

    async def _handle_finish_action(self, action: PlaybookFinishAction) -> None:
        """Handle agent finish action with completion validation."""
        if not await self._ctrl.task_validation_service.handle_finish(action):
            return
        self._ctrl.state.set_outputs(action.outputs, source="EventRouterService.finish")
        await self._ctrl.set_agent_state_to(AgentState.FINISHED)
        await self._ctrl.log_task_audit(status="success")

    async def _handle_reject_action(self, action: AgentRejectAction) -> None:
        """Handle agent reject action."""
        self._ctrl.state.set_outputs(action.outputs, source="EventRouterService.reject")
        await self._ctrl.set_agent_state_to(AgentState.REJECTED)

    async def _handle_message_action(self, action: MessageAction) -> None:
        """Handle message actions from users or agents."""
        if action.source == EventSource.USER:
            log_level = (
                "info" if os.getenv("LOG_ALL_EVENTS") in ("true", "1") else "debug"
            )
            self._ctrl.log(
                log_level,
                str(action),
                extra={"msg_type": "ACTION", "event_source": EventSource.USER},
            )
            first_user_message = self._ctrl._first_user_message()
            is_first_user_message = (
                action.id == first_user_message.id if first_user_message else False
            )
            recall_type = (
                RecallType.WORKSPACE_CONTEXT
                if is_first_user_message
                else RecallType.KNOWLEDGE
            )
            recall_action = RecallAction(query=action.content, recall_type=recall_type)
            self._ctrl._pending_action = recall_action
            self._ctrl.event_stream.add_event(recall_action, EventSource.USER)
            if self._ctrl.get_agent_state() != AgentState.RUNNING:
                await self._ctrl.set_agent_state_to(AgentState.RUNNING)
        elif action.source == EventSource.AGENT:
            if action.wait_for_response:
                await self._ctrl.set_agent_state_to(AgentState.AWAITING_USER_INPUT)

    # ── observation dispatch ──────────────────────────────────────────

    async def _handle_observation(self, observation: Observation) -> None:
        """Delegate observation handling to the observation service."""
        await self._ctrl.observation_service.handle_observation(observation)
