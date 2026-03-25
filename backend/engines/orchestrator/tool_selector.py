"""Deterministic tool selection helper.

Historically this module implemented progressive tool disclosure using keyword,
turn-count, and error-count heuristics. That path made tool availability vary
between equivalent tasks, which hurt reliability. The selector now performs a
single responsibility only: deduplicate the provided tool list while preserving
order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.core.logger import forge_logger as logger

if TYPE_CHECKING:
    from backend.controller.state.state import State


def _get_tool_name(tool: dict) -> str | None:
    """Extract the tool name from a ChatCompletionToolParam dict."""
    fn = tool.get("function", {})
    return fn.get("name")


def _dedupe_tools(all_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicate tools by function name while preserving order."""
    selected = []
    seen_names = set()
    for tool in all_tools:
        name = _get_tool_name(tool)
        if name is not None:
            if name in seen_names:
                continue
            seen_names.add(name)
        selected.append(tool)
    return selected


class ToolSelector:
    """Deduplicate tools without heuristic filtering."""

    def __init__(self) -> None:
        self._post_condensation = False

    def notify_condensation(self) -> None:
        """Retained for compatibility with callers; no longer affects selection."""
        self._post_condensation = True

    def select_tools(
        self,
        all_tools: list[dict[str, Any]],
        state: State,
        messages: list | None = None,
    ) -> list[dict[str, Any]]:
        """Return a stable, deduplicated tool list.

        Args:
            all_tools: Complete list of ChatCompletionToolParam dicts
            state: Current agent state (unused; kept for API compatibility)
            messages: Conversation messages (unused; kept for API compatibility)

        Returns:
            Deduplicated list of tool dicts
        """
        if self._post_condensation:
            logger.debug(
                "ToolSelector: ignoring legacy post-condensation heuristic path and "
                "returning the full deduplicated toolset"
            )
            self._post_condensation = False
        return _dedupe_tools(all_tools)
