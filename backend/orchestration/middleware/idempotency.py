"""Idempotency middleware — prevents duplicate action execution.

Uses the action's ``idempotency_key`` (a SHA-256 of action type + semantic
fields) to detect when the same action has already been executed in this
session.  On duplicate, the middleware blocks tool invocation and emits a
``NullObservation`` so the agent sees the skip without any side effect.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from backend.ledger.observation import Observation
from backend.orchestration.tool_pipeline import ToolInvocationMiddleware

if TYPE_CHECKING:
    from backend.orchestration.session_orchestrator import SessionOrchestrator
    from backend.orchestration.tool_pipeline import ToolInvocationContext


class IdempotencyMiddleware(ToolInvocationMiddleware):
    """Detects and blocks duplicate tool calls in the same session."""

    def __init__(self, controller: SessionOrchestrator) -> None:
        self.controller = controller
        self._seen_keys: set[str] = set()

    async def execute(self, ctx: ToolInvocationContext) -> None:
        if not ctx.action.runnable:
            return
        key = ctx.action.idempotency_key
        if not key:
            return
        if key in self._seen_keys:
            self._block_duplicate(ctx, key)
            return
        self._seen_keys.add(key)

    def _block_duplicate(
        self, ctx: ToolInvocationContext, key: str
    ) -> None:
        from backend.ledger.event import EventSource
        from backend.ledger.observation import NullObservation
        from backend.ledger.observation_cause import attach_observation_cause

        short_key = key[:12]
        action_name = type(ctx.action).__name__
        ctx.block('idempotency_duplicate')
        ctx.metadata['idempotency_key'] = key
        obs = NullObservation(content=f'[Duplicate skipped] {action_name} (hash={short_key}...)')
        attach_observation_cause(
            obs, ctx.action, context='idempotency_middleware.blocked'
        )
        self.controller.event_stream.add_event(cast(Observation, obs), EventSource.ENVIRONMENT)
        self.controller._pending_action = None
