"""Browser environment initialization — stub that always returns None.

The browser module has been removed. Browser functionality is provided
via the browser-use MCP server instead.
"""

from __future__ import annotations


async def init_browser(enable_browser: bool) -> None:  # noqa: ARG001
    """Browser support removed; always returns None."""
    return None
