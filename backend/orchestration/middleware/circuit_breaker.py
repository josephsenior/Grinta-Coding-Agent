"""Circuit breaker middleware for tool invocations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.orchestration.tool_pipeline import ToolInvocationMiddleware

if TYPE_CHECKING:
    from backend.ledger.observation import Observation
    from backend.orchestration.session_orchestrator import SessionOrchestrator
    from backend.orchestration.tool_pipeline import ToolInvocationContext

# Observation types that represent genuine progress and should reduce
# stuck-detection pressure when observed successfully.
_PROGRESS_OBSERVATION_TYPES: tuple[str, ...] = (
    'FileEditObservation',
    'FileWriteObservation',
    'AgentDelegateObservation',
    'LspQueryObservation',
)


class CircuitBreakerMiddleware(ToolInvocationMiddleware):
    """Records circuit breaker telemetry across execute/observe stages."""

    def __init__(self, controller: SessionOrchestrator) -> None:
        self.controller = controller

    async def execute(self, ctx: ToolInvocationContext) -> None:
        service = getattr(self.controller, 'circuit_breaker_service', None)
        if service:
            security_risk = getattr(ctx.action, 'security_risk', None)
            service.record_high_risk_action(security_risk)

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        service = getattr(self.controller, 'circuit_breaker_service', None)
        if not service or observation is None:
            return
        from backend.ledger.observation import ErrorObservation

        if isinstance(observation, ErrorObservation):
            service.record_error(RuntimeError(observation.content))
        else:
            service.record_success()
            # Meaningful progress actions reduce stuck-detection pressure
            obs_type = type(observation).__name__
            if obs_type in _PROGRESS_OBSERVATION_TYPES:
                service.record_progress_signal(obs_type)
