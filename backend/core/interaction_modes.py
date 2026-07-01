"""Shared interaction-mode policy for Grinta runtime surfaces."""

from __future__ import annotations

from backend.core.tools.tool_names import (
    ANALYZE_PROJECT_STRUCTURE_TOOL_NAME,
    ASK_USER_TOOL_NAME,
    DOCS_QUERY_TOOL_NAME,
    DOCS_RESOLVE_TOOL_NAME,
    FIND_SYMBOLS_TOOL_NAME,
    GLOB_TOOL_NAME,
    GREP_TOOL_NAME,
    LSP_TOOL_NAME,
    READ_FILE_TOOL_NAME,
    TASK_TRACKER_TOOL_NAME,
    WEB_FETCH_TOOL_NAME,
    WEB_SEARCH_TOOL_NAME,
)

AGENT_MODE = 'agent'
CHAT_MODE = 'chat'
PLAN_MODE = 'plan'

VISIBLE_INTERACTION_MODES = (CHAT_MODE, PLAN_MODE, AGENT_MODE)
VALID_INTERACTION_MODES = frozenset(VISIBLE_INTERACTION_MODES)

_DISCOVERY_TOOLS = frozenset(
    {
        ANALYZE_PROJECT_STRUCTURE_TOOL_NAME,
        DOCS_QUERY_TOOL_NAME,
        DOCS_RESOLVE_TOOL_NAME,
        FIND_SYMBOLS_TOOL_NAME,
        GLOB_TOOL_NAME,
        GREP_TOOL_NAME,
        LSP_TOOL_NAME,
        READ_FILE_TOOL_NAME,
        WEB_FETCH_TOOL_NAME,
        WEB_SEARCH_TOOL_NAME,
    }
)

CHAT_MODE_ALLOWED_TOOLS = _DISCOVERY_TOOLS | frozenset({ASK_USER_TOOL_NAME})

PLAN_MODE_ALLOWED_TOOLS = CHAT_MODE_ALLOWED_TOOLS | frozenset({TASK_TRACKER_TOOL_NAME})


def resolve_active_interaction_mode(
    *,
    active_run_mode: object = None,
    configured_mode: object = None,
) -> str:
    """Resolve the effective interaction mode for execution-time checks."""
    if active_run_mode:
        return normalize_interaction_mode(active_run_mode)
    return normalize_interaction_mode(configured_mode)


def action_blocked_for_interaction_mode(action: object, mode: object) -> str | None:
    """Return an error message when *action* is not allowed in *mode*."""
    from backend.ledger.action.agent import (
        BlackboardAction,
        DelegateTaskAction,
        TaskTrackingAction,
    )
    from backend.ledger.action.browse import BrowseInteractiveAction
    from backend.ledger.action.browser_tool import BrowserToolAction
    from backend.ledger.action.commands import CmdRunAction
    from backend.ledger.action.debugger import DebuggerAction
    from backend.ledger.action.files import FileEditAction
    from backend.ledger.action.mcp import MCPAction
    from backend.ledger.action.memory_tools import CheckpointAction, WorkingMemoryAction
    from backend.ledger.action.terminal import (
        TerminalCloseAction,
        TerminalInputAction,
        TerminalRunAction,
    )

    normalized = normalize_interaction_mode(mode)
    if normalized == AGENT_MODE:
        return None

    if isinstance(action, TaskTrackingAction):
        if normalized == PLAN_MODE:
            return None
        return (
            f'Tool `{TASK_TRACKER_TOOL_NAME}` is not available in Chat Mode. '
            'Switch to Plan or Agent mode to track tasks.'
        )

    agent_only_types = (
        BlackboardAction,
        BrowseInteractiveAction,
        BrowserToolAction,
        CheckpointAction,
        CmdRunAction,
        DebuggerAction,
        DelegateTaskAction,
        FileEditAction,
        MCPAction,
        TerminalCloseAction,
        TerminalInputAction,
        TerminalRunAction,
        WorkingMemoryAction,
    )
    if isinstance(action, agent_only_types):
        label = normalized.capitalize()
        return (
            f'{type(action).__name__} is not allowed in {label} mode. '
            'Switch to Agent mode to execute changes.'
        )
    return None


def normalize_interaction_mode(value: object, default: str = AGENT_MODE) -> str:
    """Normalize a configured interaction mode string."""
    mode = str(value or default).strip().lower()
    if not mode or mode not in VALID_INTERACTION_MODES:
        return default
    return mode


def is_chat_mode(value: object) -> bool:
    """Return True for chat mode where prose and grounded Q&A are allowed."""
    return normalize_interaction_mode(value) == CHAT_MODE


def is_plan_mode(value: object) -> bool:
    """Return True when the active run is a planning run."""
    return normalize_interaction_mode(value) == PLAN_MODE
