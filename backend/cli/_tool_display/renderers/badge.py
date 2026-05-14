"""Badge/icon rendering for tool call display.

Each tool type gets a visual badge that appears in the activity card.
Badges are compact and color-coded to make tool categories instantly
recognizable at a glance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from backend.cli.theme import (
    CLR_BRAND_HUE,
    CLR_CARD_BORDER,
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
    corner: str = "┌"

    def render(self) -> str:
        return f"[{self.bracket_color}]{self.corner}[/][{self.label_color} bold]{self.label}[/][{self.bracket_color}]─[/]"

    def render_left(self) -> str:
        return f"[{self.bracket_color}]{self.corner}[/][{self.label_color} bold]{self.label}[/]"


# Tool badge definitions
_BADGES: dict[str, ToolBadge] = {
    'shell': ToolBadge('Shell', CLR_STATUS_WARN, CLR_STATUS_WARN, "├"),
    'files': ToolBadge('Files', CLR_BRAND_HUE, CLR_BRAND_HUE, "├"),
    'search': ToolBadge('Search', '#b87eff', '#b87eff', "├"),
    'code': ToolBadge('Code', '#60a5fa', '#60a5fa', "├"),
    'browser': ToolBadge('Browser', '#00e5ff', '#00e5ff', "├"),
    'mcp': ToolBadge('MCP', '#f472b6', '#f472b6', "├"),
    'workers': ToolBadge('Workers', '#4ade80', '#4ade80', "├"),
    'memory': ToolBadge('Memory', '#fbbf24', '#fbbf24', "├"),
    'tasks': ToolBadge('Tasks', '#fb923c', '#fb923c', "├"),
    'think': ToolBadge('Think', CLR_SECONDARY, CLR_SECONDARY, "├"),
    'message': ToolBadge('Message', CLR_CARD_TITLE, CLR_CARD_TITLE, "├"),
    'done': ToolBadge('Done', CLR_STATUS_OK, CLR_STATUS_OK, "├"),
    'lsp': ToolBadge('LSP', '#60a5fa', '#60a5fa', "├"),
    'terminal': ToolBadge('Terminal', CLR_STATUS_WARN, CLR_STATUS_WARN, "├"),
    'checkpoint': ToolBadge('Checkpoint', CLR_CARD_TITLE, CLR_CARD_TITLE, "├"),
    'tool': ToolBadge('Tool', CLR_SECONDARY, CLR_SECONDARY, "├"),
    'recall': ToolBadge('Recall', '#fbbf24', '#fbbf24', "├"),
}

# Fallback badge
_GENERIC = ToolBadge('Tool', CLR_SECONDARY, CLR_SECONDARY, "├")


def get_tool_badge(tool_category: str) -> ToolBadge:
    """Return the badge for a tool category."""
    return _BADGES.get(tool_category.lower(), _GENERIC)


def badge_for_tool_name(tool_name: str) -> ToolBadge:
    """Infer the badge category from tool name."""
    name = tool_name.lower()

    if 'bash' in name or 'powershell' in name or 'shell' in name:
        return _BADGES['shell']
    if 'text_editor' in name or 'file' in name or 'symbol' in name:
        return _BADGES['files']
    if 'search' in name:
        return _BADGES['search']
    if 'lsp' in name or 'symbol' in name:
        return _BADGES['code']
    if 'browser' in name:
        return _BADGES['browser']
    if 'mcp' in name:
        return _BADGES['mcp']
    if 'delegate' in name or 'worker' in name:
        return _BADGES['workers']
    if 'memory' in name:
        return _BADGES['memory']
    if 'task' in name:
        return _BADGES['tasks']
    if 'think' in name or 'agent_think' in name:
        return _BADGES['think']
    if 'communicate' in name or 'message' in name:
        return _BADGES['message']
    if 'finish' in name:
        return _BADGES['done']
    if 'terminal' in name:
        return _BADGES['terminal']
    if 'checkpoint' in name:
        return _BADGES['checkpoint']

    return _GENERIC