"""Constants and regex patterns shared by the tool-call display helpers."""

from __future__ import annotations

import re

# URL detection used by the MCP preview heuristics.
_RAW_URL_RE = re.compile(r'https?://\S+', re.IGNORECASE)

# Lines that appear in raw MCP tool output but carry no signal — skipped when
# picking a preview line for the user-facing summary.
_LOW_SIGNAL_MCP_LINES = frozenset({'search results', 'results', 'content', 'text'})

# ── Orient tools ──────────────────────────────────────────────────────────────
# These are the "looked at the world" tools: flat static line tier, no border,
# no expansion, single fixed-width result column, left-ellipsis on paths.
# They share one gutter color (dim accent) distinct from write/exec tools.
ORIENT_TOOLS: frozenset[str] = frozenset(
    {
        'grep',
        'glob',
        'find_symbols',
        'read_file',
        'lsp',
        'analyze_project_structure',
        'web_search',
        'web_fetch',
        'docs_resolve',
        'docs_query',
        'checkpoint',
    }
)

# (icon, short verb phrase for the activity line)
_TOOL_HEADLINE: dict[str, tuple[str, str]] = {
    'execute_bash': ('', 'Shell'),
    'execute_powershell': ('', 'Shell'),
    'read_file': ('↳', 'Read'),
    'create_file': ('', 'Files'),
    'replace_string': ('', 'Files'),
    'multiedit': ('', 'Files'),
    'find_symbols': ('ƒ', 'Found'),
    'agent_think': ('', 'Think'),
    'think': ('', 'Think'),
    'memory': ('', 'Memory'),
    'memory_manager': ('', 'Memory'),
    'task_tracker': ('', 'Tasks'),
    'acceptance_criteria': ('', 'Criteria'),
    'grep': ('⌕', 'Grepped'),
    'glob': ('✻', 'Globbed'),
    'lsp': ('≡', 'Analyzed'),
    'analyze_project_structure': ('≡', 'Analyzed'),
    'browser': ('', 'Browser'),
    'web_search': ('⚐', 'Searched'),
    'web_fetch': ('⚐', 'Fetched'),
    'docs_resolve': ('⚐', 'Resolved'),
    'docs_query': ('⚐', 'Queried'),
    'delegate_task': ('', 'Delegate'),
    'shared_task_board': ('', 'Board'),
    'terminal_manager': ('', 'Terminal'),
    'debugger': ('', 'Debugger'),
    'ask_user': ('', 'Ask user'),
    'call_mcp_tool': ('', 'MCP'),
    'checkpoint': ('├', 'Checkpoint'),
}

# Vague placeholder summaries — when a per-tool summarizer falls back to one of
# these, the activity row is rebuilt from the tool name instead.
_VAGUE_SUMMARIES = frozenset(
    {
        '…',
        'command…',
        'file…',
        'search…',
        'LSP…',
        'directory tree',
        'scan workspace',
        'memory…',
        'tasks…',
        'AST edit…',
        'edit…',
        'terminal…',
        'debugger…',
        'board…',
        'MCP tool…',
        'revert…',
    }
)

# Cross-family history echoes the model emits as text rather than tool_calls.
_TOOL_CALL_PREFIX = '[Tool call]'
# Partial prefix that can appear mid-stream before the closing ``]`` arrives.
_TOOL_CALL_PREFIX_PARTIAL = '[Tool call'
_TOOL_RESULT_PREFIX = '[Tool result from '
_PROTOCOL_ECHO_PREFIXES = (
    _TOOL_RESULT_PREFIX,
    '[CMD_OUTPUT',
    '[Below is the output of the previous command.]',
    '[Observed result of command executed by user:',
    '[The command completed with exit code',
)

# Matches JSON objects that look like task-list items the model echoes back in text.
# Pattern: ``{"description": ..., "id": ..., "status": ...}`` (any key order).
_TASK_JSON_OBJ_RE = re.compile(
    r'\{[^{}]*"description"\s*:[^{}]*"(?:status|id)"\s*:[^{}]*\}',
    re.DOTALL,
)

# Internal protocol markers that the LLM sometimes echoes into its text response.
_INTERNAL_RESULT_MARKER_RE = re.compile(
    r'\[(?:CHECKPOINT_RESULT|REVERT_RESULT|ROLLBACK|TASK_TRACKER)\]'
    r'(?:\s*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}|\s+[^\n]*)',
)
