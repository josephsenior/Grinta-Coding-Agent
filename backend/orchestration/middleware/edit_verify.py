"""Edit verify middleware for tool invocations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.orchestration.tool_pipeline import ToolInvocationMiddleware

if TYPE_CHECKING:
    from backend.orchestration.tool_pipeline import ToolInvocationContext
    from backend.ledger.observation import Observation


class EditVerifyMiddleware(ToolInvocationMiddleware):
    """No-op: verify-after-edit hints removed to prevent verification loops."""

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        return  # The editor tool already confirms success; extra hints cause loops
