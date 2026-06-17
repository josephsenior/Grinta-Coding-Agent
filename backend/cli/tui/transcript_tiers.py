"""Transcript display tiers for TUI tool rendering.

Each tool belongs to exactly one tier with a single display rule:

- **Orient** — flat scan line, no body, no toggle
- **Artifact** — specialized body always visible (e.g. file diffs)
- **Session** — scan header + body always open (shell, terminal, debugger)
- **Record** — scan header + body collapsed by default, user expands
"""

from __future__ import annotations

from typing import Final

# Orient: read / lookup / lightweight workspace actions
ORIENT_TOOL_NAMES: Final[frozenset[str]] = frozenset(
    {
        'grep',
        'glob',
        'find_symbols',
        'read_symbols',
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

# Session: exec streams with always-open output pane
SESSION_TOOL_NAMES: Final[frozenset[str]] = frozenset(
    {
        'shell',
        'terminal',
        'debugger',
    }
)

# Record: payload stored in a collapsed body; user expands explicitly
RECORD_TOOL_NAMES: Final[frozenset[str]] = frozenset(
    {
        'browser',
        'mcp',
        'workers',
    }
)
