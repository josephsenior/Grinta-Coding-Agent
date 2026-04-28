"""Constants and regex patterns shared by the tool-call display helpers."""

from __future__ import annotations

import re

# URL detection used by the MCP preview heuristics.
_RAW_URL_RE = re.compile(r'https?://\S+', re.IGNORECASE)

# Lines that appear in raw MCP tool output but carry no signal — skipped when
# picking a preview line for the user-facing summary.
_LOW_SIGNAL_MCP_LINES = frozenset({'search results', 'results', 'content', 'text'})

# (icon, short verb phrase for the activity line)
_TOOL_HEADLINE: dict[str, tuple[str, str]] = {
    'execute_bash': ('', 'Shell'),
    'execute_powershell': ('', 'Shell'),
    'text_editor': ('', 'Files'),
    'symbol_editor': ('', 'Code edit'),
    'agent_think': ('', 'Think'),
    'think': ('', 'Think'),
    'finish': ('', 'Finish'),
    'summarize_context': ('', 'Summarize context'),
    'memory_manager': ('', 'Memory'),
    'task_tracker': ('', 'Tasks'),
    'search_code': ('', 'Search code'),
    'code_intelligence': ('', 'Code intelligence'),
    'explore_tree_structure': ('', 'Explore tree'),
    'read_symbol_definition': ('', 'Symbol'),
    'analyze_project_structure': ('', 'Analyze project'),
    'apply_patch': ('', 'Apply patch'),
    'browser': ('', 'Browser'),
    'delegate_task': ('', 'Delegate'),
    'shared_task_board': ('', 'Board'),
    'terminal_manager': ('', 'Terminal'),
    'communicate_with_user': ('', 'Message you'),
    'call_mcp_tool': ('', 'MCP'),
    'checkpoint': ('', 'Checkpoint'),
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
