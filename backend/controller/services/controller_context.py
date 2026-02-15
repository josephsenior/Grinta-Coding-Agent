from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.controller.agent_controller import AgentController
    from backend.controller.state.state_tracker import StateTracker
    from backend.controller.tool_pipeline import (
        ToolInvocationContext,
        ToolInvocationPipeline,
    )
    from backend.core.schemas import AgentState
    from backend.events import EventSource
    from backend.events.action import Action
    from backend.events.event import Event


@dataclass(slots=True)
class ControllerContext:
    """Narrow interface exposing controller capabilities to auxiliary services.

    Encapsulates direct attribute access so services interact with the controller
    through an explicit, reviewable surface. This is the first step toward a
    more formal dependency injection boundary for the controller layer.
    """

    _controller: AgentController

    @property
    def agent(self):
        """Return the controller's agent instance, if available."""
        return getattr(self._controller, "agent", None)

    @property
    def agent_config(self):
        """Return the agent configuration when present."""
        agent = self.agent
        return getattr(agent, "config", None) if agent else None

    @property
    def id(self) -> str | None:
        """Return controller identifier if available."""
        return getattr(self._controller, "id", None)

    @property
    def state(self):
        """Expose the controller state for read/write operations."""
        return getattr(self._controller, "state", None)

    @property
    def conversation_stats(self):
        return getattr(self._controller, "conversation_stats", None)

    @property
    def headless_mode(self) -> bool:
        return bool(getattr(self._controller, "headless_mode", False))

    @property
    def controller_name(self) -> str:
        agent = self.agent
        return getattr(agent, "name", "unknown") if agent else "unknown"

    @property
    def state_tracker(self) -> StateTracker | None:
        return getattr(self._controller, "state_tracker", None)

    @property
    def event_stream(self):
        """Expose the controller's event stream."""
        return getattr(self._controller, "event_stream", None)

    @property
    def pending_action(self):
        """Return currently pending action."""
        pending_service = getattr(self._controller, "pending_action_service", None)
        if pending_service:
            return pending_service.get()
        action_service = getattr(self._controller, "action_service", None)
        if action_service:
            return action_service.get_pending_action()
        return getattr(self._controller, "_pending_action", None)

    def set_pending_action(self, action: Action | None) -> None:
        action_service = getattr(self._controller, "action_service", None)
        if action_service:
            action_service.set_pending_action(action)
        else:
            setattr(self._controller, "_pending_action", action)

    def initialize_tool_pipeline(
        self, middlewares: Sequence[Any]
    ) -> ToolInvocationPipeline:
        """Attach a tool invocation pipeline to the controller.

        Resets bookkeeping caches to avoid stale context leakage.
        """
        from backend.controller.tool_pipeline import ToolInvocationPipeline

        pipeline = ToolInvocationPipeline(self._controller, list(middlewares))
        self._controller.tool_pipeline = pipeline
        self._controller._action_contexts_by_object = {}
        self._controller._action_contexts_by_event_id = {}
        return pipeline

    def cleanup_action_context(
        self,
        ctx: ToolInvocationContext,
        *,
        action: Action | None = None,
    ) -> None:
        """Proxy to the controller's context cleanup utility."""
        self._controller._cleanup_action_context(ctx, action=action)

    def emit_event(self, event: Event, source: EventSource) -> None:
        """Publish an event through the controller's event stream."""
        self._controller.event_stream.add_event(event, source)

    def clear_pending_action(self) -> None:
        """Reset the controller's pending action state."""
        self.set_pending_action(None)

    def save_state(self) -> None:
        """Persist controller state."""
        self._controller.save_state()

    def reset_controller(self) -> None:
        """Reset controller internals for STOPPED/ERROR paths."""
        self._controller._reset()

    def pop_action_context(self, event_id: int):
        mapping = getattr(self._controller, "_action_contexts_by_event_id", None)
        if mapping is None:
            return None
        return mapping.pop(event_id, None)

    async def set_agent_state(self, agent_state: AgentState) -> None:
        """Proxy to `AgentController.set_agent_state_to`."""
        await self._controller.set_agent_state_to(agent_state)

    def trigger_step(self) -> None:
        """Proxy to `AgentController.step`."""
        self._controller.step()

    @property
    def autonomy_controller(self):
        return getattr(self._controller, "autonomy_controller", None)

    @property
    def confirmation_mode(self) -> bool:
        return bool(getattr(self._controller, "confirmation_mode", False))

    @property
    def security_analyzer(self):
        return getattr(self._controller, "security_analyzer", None)

    @property
    def confirmation_service(self):
        return getattr(self._controller, "confirmation_service", None)

    @property
    def tool_pipeline(self):
        return getattr(self._controller, "tool_pipeline", None)

    @property
    def iteration_service(self):
        return getattr(self._controller, "iteration_service", None)

    @property
    def telemetry_service(self):
        return getattr(self._controller, "telemetry_service", None)

    @property
    def metrics_service(self):
        """Access agent performance metrics service."""
        services = getattr(self._controller, "services", None)
        return getattr(services, "metrics", None) if services else None

    def register_action_context(
        self, action: Action, ctx: ToolInvocationContext
    ) -> None:
        self._controller._register_action_context(action, ctx)

    async def run_action(
        self, action: Action, ctx: ToolInvocationContext | None
    ) -> None:
        await self._controller.action_service.run(action, ctx)

    def get_controller(self) -> AgentController:
        """Expose the underlying controller instance."""
        return self._controller
