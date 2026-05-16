"""Per-tool renderers for Grinta agentic UI.

Each tool category has a dedicated renderer that produces rich,
structured output with badges, parsed results, and smart formatting.
"""

from __future__ import annotations

from backend.cli._tool_display.renderers.badge import (
    ToolBadge,
    badge_for_tool_name,
    get_tool_badge,
)
from backend.cli._tool_display.renderers.browser import (
    render_browser_navigation,
    render_browser_page,
)
from backend.cli._tool_display.renderers.delegation import (
    render_delegation,
)
from backend.cli._tool_display.renderers.file_editor import (
    render_file_create,
    render_file_edit,
    render_file_read,
)
from backend.cli._tool_display.renderers.finish import (
    render_finish_summary,
)
from backend.cli._tool_display.renderers.lsp import (
    render_lsp_query,
)
from backend.cli._tool_display.renderers.mcp import (
    render_mcp_tool,
)
from backend.cli._tool_display.renderers.memory import (
    render_memory_update,
)
from backend.cli._tool_display.renderers.search import (
    render_search_results,
    render_search_summary,
)
from backend.cli._tool_display.renderers.shell import (
    render_shell_command,
)
from backend.cli._tool_display.renderers.tasks import (
    render_task_list,
    render_task_summary,
)
from backend.cli._tool_display.renderers.terminal import (
    render_browser_screenshot,
    render_condensation_action,
    render_condensation_complete,
    render_delegation_action,
    render_delegation_result,
    render_file_download,
    render_lsp_result,
    render_server_ready,
    render_terminal_output,
    render_terminal_read,
    render_user_reject,
)

__all__ = [
    'ToolBadge',
    'badge_for_tool_name',
    'get_tool_badge',
    'render_file_edit',
    'render_file_read',
    'render_file_create',
    'render_shell_command',
    'render_search_results',
    'render_search_summary',
    'render_finish_summary',
    'render_mcp_tool',
    'render_lsp_query',
    'render_browser_navigation',
    'render_browser_page',
    'render_delegation',
    'render_memory_update',
    'render_task_list',
    'render_task_summary',
    'render_terminal_read',
    'render_terminal_output',
    'render_browser_screenshot',
    'render_lsp_result',
    'render_delegation_action',
    'render_delegation_result',
    'render_condensation_action',
    'render_condensation_complete',
    'render_user_reject',
    'render_server_ready',
    'render_file_download',
]
