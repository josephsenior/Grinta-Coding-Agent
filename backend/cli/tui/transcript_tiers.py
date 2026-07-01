"""Transcript display tiers for TUI tool rendering.

The live TUI renders tool activity in exactly two tiers:

- **Orient** — a flat single-line :class:`OrientLine` row (no body, no
  expansion). Used for lightweight reads / lookups. See
  :data:`ORIENT_TOOL_NAMES`.
- **Action** — a single-line :class:`ScanLineCard` summary with a state-colored
  left pipe and a ``⤢`` affordance. The full payload (diff, output, scrollback,
  stack, result) lives in a pushed full-screen ``DetailScreen``; the feed row
  itself never grows. Used for everything heavier than an orient read. See
  :data:`ACTION_TOOL_NAMES`.

There is no inline collapsed/expanded body in the live feed — expansion always
means a detail screen on the screen stack (open with Enter/Space on a focused
card, the ``⤢`` button, or a click).

These name sets are a reference for which tier a tool belongs to. They are not
imported by the render pipeline (which keys off event/observation types in
``renderer/handlers``); keep them in sync as a documentation aid.
"""

from __future__ import annotations

from typing import Final

# Orient: read / lookup / lightweight workspace actions → OrientLine
ORIENT_TOOL_NAMES: Final[frozenset[str]] = frozenset(
    {
        'grep',
        'glob',
        'find_symbols',
        'read_file',
        'read_symbol',
        'lsp',
        'analyze_project_structure',
        'web_search',
        'web_fetch',
        'docs_resolve',
        'docs_query',
        'checkpoint',
    }
)

# Action: everything heavier → ScanLineCard (1-line summary) + DetailScreen
ACTION_TOOL_NAMES: Final[frozenset[str]] = frozenset(
    {
        'shell',
        'terminal',
        'debugger',
        'browser',
        'mcp',
        'workers',
        'condensation',
    }
)
