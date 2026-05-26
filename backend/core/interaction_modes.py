"""Shared interaction-mode policy for Grinta runtime surfaces."""

from __future__ import annotations

AGENT_MODE = 'agent'
ASK_MODE = 'ask'
CHAT_MODE = 'chat'
PLAN_MODE = 'plan'

CHAT_MODE_NAMES = frozenset({CHAT_MODE, ASK_MODE})
VISIBLE_INTERACTION_MODES = (CHAT_MODE, PLAN_MODE, AGENT_MODE)
VALID_INTERACTION_MODES = frozenset({*VISIBLE_INTERACTION_MODES, ASK_MODE})

CHAT_MODE_ALLOWED_TOOLS = frozenset(
    {
        'analyze_project_structure',
        'find_symbols',
        'lsp',
        'read',
        'recall',
        'search_code',
    }
)

PLAN_MODE_ALLOWED_TOOLS = frozenset(
    {
        'analyze_project_structure',
        'communicate_with_user',
        'find_symbols',
        'finish',
        'lsp',
        'read',
        'recall',
        'search_code',
    }
)


def normalize_interaction_mode(value: object, default: str = AGENT_MODE) -> str:
    """Normalize a configured interaction mode string."""
    mode = str(value or default).strip().lower()
    if not mode or mode not in VALID_INTERACTION_MODES:
        return default
    return mode


def is_chat_mode(value: object) -> bool:
    """Return True for chat-like modes where plain prose is allowed."""
    return normalize_interaction_mode(value) in CHAT_MODE_NAMES


def is_plan_mode(value: object) -> bool:
    """Return True when the active run is a read-only planning run."""
    return normalize_interaction_mode(value) == PLAN_MODE
