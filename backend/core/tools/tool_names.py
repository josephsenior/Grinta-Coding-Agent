"""Canonical runtime tool name constants for function calling.

Every agent-facing tool name is defined here once. Tool modules, the planner,
prompt renderers, and dispatch maps should import from this module rather than
declaring parallel ``*_TOOL_NAME`` literals.
"""

from __future__ import annotations

# ── File API ────────────────────────────────────────────────────────
READ_FILE_TOOL_NAME = 'read_file'
READ_SYMBOL_TOOL_NAME = 'read_symbols'
FIND_SYMBOLS_TOOL_NAME = 'find_symbols'
CREATE_FILE_TOOL_NAME = 'create_file'
REPLACE_STRING_TOOL_NAME = 'replace_string'
MULTIEDIT_TOOL_NAME = 'multiedit'
UNDO_LAST_EDIT_TOOL_NAME = 'undo_last_edit'

# ── Search & project structure ────────────────────────────────────────
GREP_TOOL_NAME = 'grep'
GLOB_TOOL_NAME = 'glob'
LSP_TOOL_NAME = 'lsp'
ANALYZE_PROJECT_STRUCTURE_TOOL_NAME = 'analyze_project_structure'

# ── Shell & terminal ──────────────────────────────────────────────────
EXECUTE_BASH_TOOL_NAME = 'execute_bash'
EXECUTE_POWERSHELL_TOOL_NAME = 'execute_powershell'
TERMINAL_MANAGER_TOOL_NAME = 'terminal_manager'

# ── Agent interaction & planning ────────────────────────────────────────
ASK_USER_TOOL_NAME = 'ask_user'
TASK_TRACKER_TOOL_NAME = 'task_tracker'

# ── Memory & checkpoints ──────────────────────────────────────────────
MEMORY_TOOL_NAME = 'memory'
CHECKPOINT_TOOL_NAME = 'checkpoint'
# Internal-only legacy names (not exposed to the LLM tool surface).
NOTE_TOOL_NAME = 'note'
RECALL_TOOL_NAME = 'recall'
MEMORY_MANAGER_TOOL_NAME = MEMORY_TOOL_NAME

# ── Web & MCP ───────────────────────────────────────────────────────
WEB_SEARCH_TOOL_NAME = 'web_search'
WEB_FETCH_TOOL_NAME = 'web_fetch'
DOCS_RESOLVE_TOOL_NAME = 'docs_resolve'
DOCS_QUERY_TOOL_NAME = 'docs_query'
CALL_MCP_TOOL_NAME = 'call_mcp_tool'
BROWSER_TOOL_NAME = 'browser'
DEBUGGER_TOOL_NAME = 'debugger'
DELEGATE_TASK_TOOL_NAME = 'delegate_task'
SHARED_TASK_BOARD_TOOL_NAME = 'shared_task_board'

# ── Legacy aliases (prefer the canonical names above in new code) ─────
CODE_INTELLIGENCE_TOOL_NAME = LSP_TOOL_NAME
EXECUTE_MCP_TOOL_TOOL_NAME = CALL_MCP_TOOL_NAME
BLACKBOARD_TOOL_NAME = SHARED_TASK_BOARD_TOOL_NAME

__all__ = [
    'ANALYZE_PROJECT_STRUCTURE_TOOL_NAME',
    'ASK_USER_TOOL_NAME',
    'BLACKBOARD_TOOL_NAME',
    'BROWSER_TOOL_NAME',
    'CALL_MCP_TOOL_NAME',
    'CHECKPOINT_TOOL_NAME',
    'CODE_INTELLIGENCE_TOOL_NAME',
    'CREATE_FILE_TOOL_NAME',
    'DEBUGGER_TOOL_NAME',
    'DOCS_QUERY_TOOL_NAME',
    'DOCS_RESOLVE_TOOL_NAME',
    'DELEGATE_TASK_TOOL_NAME',
    'EXECUTE_BASH_TOOL_NAME',
    'EXECUTE_MCP_TOOL_TOOL_NAME',
    'EXECUTE_POWERSHELL_TOOL_NAME',
    'FIND_SYMBOLS_TOOL_NAME',
    'GLOB_TOOL_NAME',
    'GREP_TOOL_NAME',
    'LSP_TOOL_NAME',
    'MEMORY_MANAGER_TOOL_NAME',
    'MEMORY_TOOL_NAME',
    'MULTIEDIT_TOOL_NAME',
    'NOTE_TOOL_NAME',
    'READ_FILE_TOOL_NAME',
    'READ_SYMBOL_TOOL_NAME',
    'RECALL_TOOL_NAME',
    'REPLACE_STRING_TOOL_NAME',
    'SHARED_TASK_BOARD_TOOL_NAME',
    'TASK_TRACKER_TOOL_NAME',
    'TERMINAL_MANAGER_TOOL_NAME',
    'UNDO_LAST_EDIT_TOOL_NAME',
    'WEB_FETCH_TOOL_NAME',
    'WEB_SEARCH_TOOL_NAME',
]
