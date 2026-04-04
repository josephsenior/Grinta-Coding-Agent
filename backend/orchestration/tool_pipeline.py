"""Tool invocation pipeline and base middleware.

Concrete middleware implementations live in backend.orchestration.middleware.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from backend.core.logger import app_logger as logger

if TYPE_CHECKING:
    from backend.ledger.action import Action
    from backend.ledger.observation import Observation
    from backend.orchestration.session_orchestrator import SessionOrchestrator
    from backend.orchestration.state.state import State


@dataclass
class ToolInvocationContext:
    """Context shared across middleware stages during a tool invocation."""

    controller: SessionOrchestrator
    action: Action
    state: State
    metadata: dict[str, Any] = field(default_factory=dict)
    blocked: bool = False
    block_reason: str | None = None
    action_id: int | None = None

    def block(self, reason: str | None = None) -> None:
        """Mark the invocation as blocked to stop subsequent stages."""
        self.blocked = True
        if reason:
            self.block_reason = reason


class ToolInvocationMiddleware:
    """Base middleware with optional lifecycle hooks."""

    async def plan(
        self, ctx: ToolInvocationContext
    ) -> None:  # pragma: no cover - default no-op
        return None

    async def verify(
        self, ctx: ToolInvocationContext
    ) -> None:  # pragma: no cover - default no-op
        return None

    async def execute(
        self, ctx: ToolInvocationContext
    ) -> None:  # pragma: no cover - default no-op
        return None

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:  # pragma: no cover - default no-op
        return None


class ToolInvocationPipeline:
    """Runs middleware stages (plan → verify → execute → observe) for tool calls."""

    def __init__(
        self,
        controller: SessionOrchestrator,
        middlewares: Iterable[ToolInvocationMiddleware],
    ) -> None:
        self.controller = controller
        self.middlewares = list(middlewares)

    def create_context(self, action: Action, state: State) -> ToolInvocationContext:
        """Create a new invocation context for the given action."""
        return ToolInvocationContext(
            controller=self.controller,
            action=action,
            state=state,
        )

    async def run_plan(self, ctx: ToolInvocationContext) -> None:
        await self._run_stage('plan', ctx)

    async def run_verify(self, ctx: ToolInvocationContext) -> None:
        if ctx.blocked:
            return
        await self._run_stage('verify', ctx)

    async def run_execute(self, ctx: ToolInvocationContext) -> None:
        if ctx.blocked:
            return
        await self._run_stage('execute', ctx)

    async def run_observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        ctx.metadata['observation'] = observation
        await self._run_stage('observe', ctx, observation=observation)

    async def _run_stage(
        self,
        stage: str,
        ctx: ToolInvocationContext,
        **kwargs: Any,
    ) -> None:
        handler_name = stage
        for middleware in self.middlewares:
            if ctx.blocked:
                break
            handler = getattr(middleware, handler_name, None)
            if handler is None:
                continue
            try:
                result = handler(ctx, **kwargs) if kwargs else handler(ctx)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception(
                    'Tool middleware %s failed during stage %s: %s',
                    middleware.__class__.__name__,
                    stage,
                    exc,
                )
                ctx.block(reason=f'{middleware.__class__.__name__}:{stage}_error')
                break


# Re-exports for backward compatibility. Import from backend.orchestration.middleware
# for new code.
def __getattr__(name: str) -> Any:
    if name in (
        'AutoCheckMiddleware',
        'BlackboardMiddleware',
        'CircuitBreakerMiddleware',
        'ConflictDetectionMiddleware',
        'ContextWindowMiddleware',
        'CostQuotaMiddleware',
        'EditVerifyMiddleware',
        'ErrorPatternMiddleware',
        'LoggingMiddleware',
        'ReflectionMiddleware',
        'SafetyValidatorMiddleware',
        'TelemetryMiddleware',
    ):
        from backend.orchestration import middleware as mw

        return getattr(mw, name)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


__all__ = [
    'ToolInvocationContext',
    'ToolInvocationMiddleware',
    'ToolInvocationPipeline',
]
