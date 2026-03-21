"""Error pattern middleware for tool invocations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.controller.tool_pipeline import ToolInvocationMiddleware

if TYPE_CHECKING:
    from backend.controller.tool_pipeline import ToolInvocationContext
    from backend.events.observation import Observation


class ErrorPatternMiddleware(ToolInvocationMiddleware):
    """Auto-queries the query_error_solutions DB when an ErrorObservation arrives.

    Eliminates the need for the LLM to remember to call query_error_solutions(query)
    every time it hits an error.  If a known fix exists, it is appended
    directly to the observation so the LLM sees it on the next turn.
    """

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        if observation is None:
            return
        from backend.events.observation import ErrorObservation

        if not isinstance(observation, ErrorObservation):
            return

        content = getattr(observation, "content", "") or ""
        if not content:
            return

        try:
            from backend.engines.orchestrator.tools.query_error_solutions import _query_patterns

            result_action = _query_patterns(content)
            result_text = getattr(result_action, "thought", "")
            # Only append if a known pattern was found
            if "No known patterns" not in result_text and result_text:
                observation.content = (
                    content
                    + "\n\n<KNOWN_FIX>"
                    + "\n" + result_text
                    + "\n</KNOWN_FIX>"
                )
        except Exception:
            pass  # Non-critical — never let this break error handling
