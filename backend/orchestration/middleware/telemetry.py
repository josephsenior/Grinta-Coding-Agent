"""Telemetry middleware for tool invocations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.orchestration.tool_pipeline import ToolInvocationMiddleware
from backend.orchestration.tool_telemetry import ToolTelemetry

if TYPE_CHECKING:
    from backend.ledger.observation import Observation
    from backend.orchestration.session_orchestrator import SessionOrchestrator
    from backend.orchestration.tool_pipeline import ToolInvocationContext


class TelemetryMiddleware(ToolInvocationMiddleware):
    """Emit telemetry events for tool invocations."""

    def __init__(self, controller: SessionOrchestrator) -> None:
        self.controller = controller
        self.telemetry = ToolTelemetry.get_instance()

    async def execute(self, ctx: ToolInvocationContext) -> None:
        if ctx.blocked:
            return
        self.telemetry.on_execute(ctx)

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        self.telemetry.on_observe(ctx, observation)
