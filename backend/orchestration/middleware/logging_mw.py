"""Logging middleware for tool invocations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.constants import LOG_ALL_EVENTS
from backend.orchestration.tool_pipeline import ToolInvocationMiddleware

if TYPE_CHECKING:
    from backend.ledger.observation import Observation
    from backend.orchestration.session_orchestrator import SessionOrchestrator
    from backend.orchestration.tool_pipeline import ToolInvocationContext


class LoggingMiddleware(ToolInvocationMiddleware):
    """Emits structured logs for each pipeline stage."""

    def __init__(self, controller: SessionOrchestrator) -> None:
        self.controller = controller

    async def execute(self, ctx: ToolInvocationContext) -> None:
        self.controller.log(
            'debug',
            f'[EXECUTE] {type(ctx.action).__name__}',
            extra={'msg_type': 'PIPELINE_EXECUTE'},
        )

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        if observation is None:
            return
        log_level = 'info' if LOG_ALL_EVENTS else 'debug'
        self.controller.log(
            log_level,
            f'[OBSERVE] {observation}',
            extra={'msg_type': 'PIPELINE_OBSERVE'},
        )
