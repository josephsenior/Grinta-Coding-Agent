"""Shared interaction-mode policy for Grinta runtime surfaces."""

from __future__ import annotations

AGENT_MODE = 'agent'
CHAT_MODE = 'chat'
PLAN_MODE = 'plan'

VISIBLE_INTERACTION_MODES = (CHAT_MODE, PLAN_MODE, AGENT_MODE)
VALID_INTERACTION_MODES = frozenset(VISIBLE_INTERACTION_MODES)

from backend.inference.tool_names import (
    ANALYZE_PROJECT_STRUCTURE_TOOL_NAME,
    ASK_USER_TOOL_NAME,
    FIND_SYMBOLS_TOOL_NAME,
    GLOB_TOOL_NAME,
    GREP_TOOL_NAME,
    LSP_TOOL_NAME,
    READ_TOOL_NAME,
    TASK_TRACKER_TOOL_NAME,
    WEB_FETCH_TOOL_NAME,
    WEB_SEARCH_TOOL_NAME,
)

_DISCOVERY_TOOLS = frozenset(
    {
        ANALYZE_PROJECT_STRUCTURE_TOOL_NAME,
        FIND_SYMBOLS_TOOL_NAME,
        GLOB_TOOL_NAME,
        GREP_TOOL_NAME,
        LSP_TOOL_NAME,
        READ_TOOL_NAME,
        WEB_FETCH_TOOL_NAME,
        WEB_SEARCH_TOOL_NAME,
    }
)

CHAT_MODE_ALLOWED_TOOLS = _DISCOVERY_TOOLS | frozenset({ASK_USER_TOOL_NAME})

PLAN_MODE_ALLOWED_TOOLS = CHAT_MODE_ALLOWED_TOOLS | frozenset({TASK_TRACKER_TOOL_NAME})


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
