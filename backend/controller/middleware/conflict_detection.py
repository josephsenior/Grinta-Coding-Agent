"""Conflict detection middleware for tool invocations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.controller.tool_pipeline import ToolInvocationMiddleware

if TYPE_CHECKING:
    from backend.controller.tool_pipeline import ToolInvocationContext
    from backend.events.observation import Observation


class ConflictDetectionMiddleware(ToolInvocationMiddleware):
    """Warns when the agent re-edits a file without verifying it first.

    Tracks which files have been edited and read in the current session.
    When the agent edits a file that was already edited without a subsequent
    read/view, a warning is prepended to the observation reminding the LLM
    to verify its mental model before making further edits.
    """

    def __init__(self) -> None:
        # {path: edit_count_since_last_view}
        self._unverified_edits: dict[str, int] = {}

    async def verify(self, ctx: ToolInvocationContext) -> None:
        """No-op: conflict blocking removed to prevent verification loops."""
        return

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        return  # No-op: conflict warnings removed to prevent verification loops
