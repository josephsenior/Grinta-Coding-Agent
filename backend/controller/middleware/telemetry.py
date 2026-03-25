"""Telemetry middleware for tool invocations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.controller.tool_pipeline import ToolInvocationMiddleware
from backend.controller.tool_telemetry import ToolTelemetry

if TYPE_CHECKING:
    from backend.controller.agent_controller import AgentController
    from backend.controller.tool_pipeline import ToolInvocationContext
    from backend.events.observation import Observation


class TelemetryMiddleware(ToolInvocationMiddleware):
    """Emit telemetry events for tool invocations."""

    def __init__(self, controller: AgentController) -> None:
        self.controller = controller
        self.telemetry = ToolTelemetry.get_instance()

    async def plan(self, ctx: ToolInvocationContext) -> None:
        self.telemetry.on_plan(ctx)

    async def execute(self, ctx: ToolInvocationContext) -> None:
        if ctx.blocked:
            return
        self.telemetry.on_execute(ctx)

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        self.telemetry.on_observe(ctx, observation)
