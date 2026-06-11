"""Badge/icon rendering for tool call display.

Each tool type gets a visual badge that appears in the activity card.
Badges are compact and color-coded to make tool categories instantly
recognizable at a glance.

Consolidated to 6 semantic categories for reduced visual noise:
- Execution (Shell, Terminal) — warm yellow
- Files (read, edit, create) — periwinkle blue
- Search — purple
- Code (LSP, analysis) — blue
- External (Browser, MCP) — cyan/pink merged to teal
- System (Workers, Memory, Tasks, Think) — green
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.cli.theme import (
    CLR_BRAND_HUE,
    CLR_CARD_TITLE,
    CLR_SECONDARY,
    CLR_STATUS_ERR,
    CLR_STATUS_OK,
    CLR_STATUS_WARN,
)


@dataclass
class ToolBadge:
    """A visual badge for a tool category."""

    label: str
    bracket_color: str
    label_color: str
    corner: str = '┌'

    def render(self) -> str:
        return f'[{self.bracket_color}]{self.corner}[/][{self.label_color} bold]{self.label}[/][{self.bracket_color}]─[/]'

    def render_left(self) -> str:
        return f'[{self.bracket_color}]{self.corner}[/][{self.label_color} bold]{self.label}[/]'


# Consolidated badge definitions — 6 semantic categories
_BADGES: dict[str, ToolBadge] = {
    # Execution: shell commands, terminal operations
    'shell': ToolBadge('Shell', CLR_STATUS_WARN, CLR_STATUS_WARN, '├'),
    'terminal': ToolBadge('Terminal', CLR_STATUS_WARN, CLR_STATUS_WARN, '├'),
    # Files: read, edit, create operations
    'files': ToolBadge('Files', CLR_BRAND_HUE, CLR_BRAND_HUE, '├'),
    # Search: code search, grep
    'search': ToolBadge('Search', '#b87eff', '#b87eff', '├'),
    # Code: LSP, analysis, symbols
    'code': ToolBadge('Code', '#60a5fa', '#60a5fa', '├'),
    'lsp': ToolBadge('LSP', '#60a5fa', '#60a5fa', '├'),
    # External: browser, MCP servers
    'browser': ToolBadge('Browser', '#48b8c8', '#48b8c8', '├'),
    'mcp': ToolBadge('MCP', '#48b8c8', '#48b8c8', '├'),
    # System: workers, memory, tasks, thinking
    'workers': ToolBadge('Workers', CLR_STATUS_OK, CLR_STATUS_OK, '├'),
    'memory': ToolBadge('Memory', CLR_STATUS_OK, CLR_STATUS_OK, '├'),
    'tasks': ToolBadge('Tasks', CLR_STATUS_OK, CLR_STATUS_OK, '├'),
    'think': ToolBadge('Think', CLR_SECONDARY, CLR_SECONDARY, '├'),
    'message': ToolBadge('Message', CLR_CARD_TITLE, CLR_CARD_TITLE, '├'),
    'done': ToolBadge('Done', CLR_STATUS_OK, CLR_STATUS_OK, '├'),
    'checkpoint': ToolBadge('Checkpoint', CLR_CARD_TITLE, CLR_CARD_TITLE, '├'),
    'tool': ToolBadge('Tool', CLR_SECONDARY, CLR_SECONDARY, '├'),
    'recall': ToolBadge('Recall', CLR_STATUS_OK, CLR_STATUS_OK, '├'),
    'error': ToolBadge('Error', CLR_STATUS_ERR, CLR_STATUS_ERR, '├'),
}

# Fallback badge
_GENERIC = ToolBadge('Tool', CLR_SECONDARY, CLR_SECONDARY, '├')


def get_tool_badge(tool_category: str) -> ToolBadge:
    """Return the badge for a tool category."""
    return _BADGES.get(tool_category.lower(), _GENERIC)


_NAME_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (('error',), 'error'),
    (('bash', 'powershell', 'shell'), 'shell'),
    (('file', 'symbol'), 'files'),
    (('search',), 'search'),
    (('lsp', 'symbol'), 'code'),
    (('browser',), 'browser'),
    (('mcp',), 'mcp'),
    (('delegate', 'worker'), 'workers'),
    (('memory',), 'memory'),
    (('task',), 'tasks'),
    (('think', 'agent_think'), 'think'),
    (('communicate', 'message'), 'message'),
    (('terminal',), 'terminal'),
    (('checkpoint',), 'checkpoint'),
)


def badge_for_tool_name(tool_name: str) -> ToolBadge:
    """Infer the badge category from tool name."""
    name = tool_name.lower()
    for keywords, badge_key in _NAME_RULES:
        for kw in keywords:
            if kw in name:
                return _BADGES[badge_key]
    return _GENERIC
