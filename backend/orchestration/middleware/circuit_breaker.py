"""Circuit breaker middleware for tool invocations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.orchestration.tool_pipeline import ToolInvocationMiddleware

if TYPE_CHECKING:
    from backend.orchestration.session_orchestrator import SessionOrchestrator
    from backend.orchestration.tool_pipeline import ToolInvocationContext
    from backend.ledger.observation import Observation


class CircuitBreakerMiddleware(ToolInvocationMiddleware):
    """Records circuit breaker telemetry across execute/observe stages."""

    def __init__(self, controller: SessionOrchestrator) -> None:
        self.controller = controller

    async def execute(self, ctx: ToolInvocationContext) -> None:
        service = getattr(self.controller, "circuit_breaker_service", None)
        if service:
            security_risk = getattr(ctx.action, "security_risk", None)
            service.record_high_risk_action(security_risk)

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        service = getattr(self.controller, "circuit_breaker_service", None)
        if not service or observation is None:
            return
        from backend.ledger.observation import ErrorObservation

        if isinstance(observation, ErrorObservation):
            service.record_error(RuntimeError(observation.content))
        else:
            service.record_success()
