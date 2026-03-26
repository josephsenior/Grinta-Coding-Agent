"""Blackboard middleware for tool invocations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.controller.tool_pipeline import ToolInvocationMiddleware

if TYPE_CHECKING:
    from backend.controller.agent_controller import AgentController
    from backend.controller.tool_pipeline import ToolInvocationContext


class BlackboardMiddleware(ToolInvocationMiddleware):
    """Handle BlackboardAction in-process when controller has a shared blackboard (delegate workers)."""

    def __init__(self, controller: AgentController) -> None:
        self.controller = controller

    async def execute(self, ctx: ToolInvocationContext) -> None:
        from backend.events.action.agent import BlackboardAction
        from backend.events.event import EventSource
        from backend.events.observation import AgentThinkObservation, ErrorObservation
        from backend.events.observation_cause import attach_observation_cause

        if not isinstance(ctx.action, BlackboardAction):
            return
        blackboard = getattr(self.controller.config, "blackboard", None)
        if blackboard is None:
            from backend.controller.blackboard import Blackboard
            blackboard = Blackboard()

        # If it somehow still fails
        if blackboard is None:
            ctx.block("blackboard_not_available")
            ctx.metadata["handled"] = True
            err = ErrorObservation(
                content="[BLACKBOARD] No shared blackboard in this session.",
                error_id="BLACKBOARD_UNAVAILABLE",
            )
            attach_observation_cause(
                err, ctx.action, context="blackboard.unavailable"
            )
            err.tool_call_metadata = getattr(ctx.action, "tool_call_metadata", None)
            self.controller.event_stream.add_event(err, EventSource.ENVIRONMENT)
            return
        cmd = (getattr(ctx.action, "command", "get") or "get").lower()
        key = (getattr(ctx.action, "key", "") or "").strip()
        value = (getattr(ctx.action, "value", "") or "").strip()
        try:
            if cmd == "get":
                result = await blackboard.get(key or None)
                if isinstance(result, dict):
                    text = "\n".join(f"  {k}: {v}" for k, v in result.items()) or "(empty)"
                else:
                    text = str(result)
                content = f"[BLACKBOARD] get {key or 'all'}:\n{text}"
            elif cmd == "set":
                if not key:
                    content = "[BLACKBOARD] set requires a non-empty key."
                else:
                    await blackboard.set(key, value)
                    content = f"[BLACKBOARD] set {key!r} = {value!r}"
            elif cmd == "keys":
                keys = await blackboard.keys()
                content = f"[BLACKBOARD] keys: {keys}"
            else:
                content = f"[BLACKBOARD] unknown command: {cmd}"
            obs = AgentThinkObservation(content=content)
            attach_observation_cause(obs, ctx.action, context="blackboard.result")
            obs.tool_call_metadata = getattr(ctx.action, "tool_call_metadata", None)
            self.controller.event_stream.add_event(obs, EventSource.ENVIRONMENT)
            ctx.block("blackboard_handled")
            ctx.metadata["handled"] = True
        except Exception as e:
            ctx.block("blackboard_error")
            ctx.metadata["handled"] = True
            err = ErrorObservation(
                content=f"[BLACKBOARD] Error: {e}",
                error_id="BLACKBOARD_ERROR",
            )
            attach_observation_cause(
                err, ctx.action, context="blackboard.exception"
            )
            err.tool_call_metadata = getattr(ctx.action, "tool_call_metadata", None)
            self.controller.event_stream.add_event(err, EventSource.ENVIRONMENT)
