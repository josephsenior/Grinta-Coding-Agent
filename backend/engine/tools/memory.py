"""Unified memory tool — session working state, workspace persistence, and recall."""

from __future__ import annotations

from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.common import create_tool_definition
from backend.inference.tool_names import MEMORY_TOOL_NAME

_MEMORY_DESCRIPTION = (
    'Unified memory for this agent.\n\n'
    '**working** — session-scoped cognitive state (hypothesis, findings, blockers, '
    'file_context, decisions, plan). Survives context condensation within the session. '
    'Use update_type=get|update|clear_section with section and content.\n\n'
    '**persist** — workspace-scoped durable facts (conventions, commands, architecture, '
    'lessons). Rare; only for verified repo facts worth keeping across sessions.\n\n'
    '**recall** — fuzzy search across indexed conversation history when the visible '
    'window no longer shows what you need. Pass key as the search phrase.'
)


def create_memory_tool() -> ChatCompletionToolParam:
    """Create the unified memory tool definition."""
    return create_tool_definition(
        name=MEMORY_TOOL_NAME,
        description=_MEMORY_DESCRIPTION,
        properties={
            'action': {
                'type': 'string',
                'enum': ['working', 'persist', 'recall'],
                'description': (
                    'Memory operation: working (session state), persist (workspace facts), '
                    'or recall (semantic search over indexed history).'
                ),
            },
            'key': {
                'type': 'string',
                'description': (
                    'For persist: short identifier. For recall: natural-language search phrase.'
                ),
            },
            'kind': {
                'type': 'string',
                'enum': ['convention', 'command', 'architecture', 'lesson'],
                'description': "Category for persist (default 'lesson').",
            },
            'value': {
                'type': 'string',
                'description': 'Content to store for persist.',
            },
            'update_type': {
                'type': 'string',
                'enum': ['update', 'get', 'clear_section'],
                'description': "Operation for working memory (default 'get').",
            },
            'section': {
                'type': 'string',
                'enum': [
                    'hypothesis',
                    'findings',
                    'blockers',
                    'file_context',
                    'decisions',
                    'plan',
                    'all',
                ],
                'description': "Working-memory section (default 'all').",
            },
            'content': {
                'type': 'string',
                'description': "Content for working memory update_type='update'.",
            },
        },
        required=['action'],
    )


# Backward-compatible factory name for imports not yet updated.
create_memory_manager_tool = create_memory_tool

__all__ = ['create_memory_tool', 'create_memory_manager_tool']
