"""Logging middleware for tool invocations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.controller.tool_pipeline import ToolInvocationMiddleware
from backend.core.constants import LOG_ALL_EVENTS

if TYPE_CHECKING:
    from backend.controller.agent_controller import AgentController
    from backend.controller.tool_pipeline import ToolInvocationContext
    from backend.events.observation import Observation


class LoggingMiddleware(ToolInvocationMiddleware):
    """Emits structured logs for each pipeline stage."""

    def __init__(self, controller: AgentController) -> None:
        self.controller = controller

    async def plan(self, ctx: ToolInvocationContext) -> None:
        self.controller.log(
            "debug",
            f"[PLAN] {type(ctx.action).__name__}",
            extra={"msg_type": "PIPELINE_PLAN"},
        )

    async def execute(self, ctx: ToolInvocationContext) -> None:
        self.controller.log(
            "debug",
            f"[EXECUTE] {type(ctx.action).__name__}",
            extra={"msg_type": "PIPELINE_EXECUTE"},
        )

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        if observation is None:
            return
        log_level = "info" if LOG_ALL_EVENTS else "debug"
        self.controller.log(
            log_level,
            f"[OBSERVE] {observation}",
            extra={"msg_type": "PIPELINE_OBSERVE"},
        )
