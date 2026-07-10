"""Unified memory tool — session working state, workspace persistence, and recall."""

from __future__ import annotations

from backend.core.tools.tool_names import MEMORY_TOOL_NAME
from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.param_defs import create_tool_definition

_MEMORY_DESCRIPTION_BASE = (
    'Unified memory for this agent.\n\n'
    '**working** — session-scoped cognitive state (hypothesis, findings, blockers, '
    'file_context, decisions, plan). Survives context condensation within the session. '
    'Use update_type=get|update|clear_section with section and content.\n\n'
    '**persist** — workspace-scoped durable facts that survive across sessions. '
    'Tactical kinds: `convention`, `command`, `architecture`, `lesson` (verified repo facts). '
    'Strategic kinds: `strategy` (cross-cutting approach), `heuristic` (reusable "if X then Y" rule), '
    '`decision` (recorded choice + rationale), `preference` (user working style). '
    'Rare; only for verified knowledge worth keeping across sessions.'
)

_MEMORY_RECALL_BLOCK = (
    '\n\n'
    '**recall** — fuzzy search across indexed conversation history when the visible '
    'window no longer shows what you need. Pass key as the search phrase.'
)


def create_memory_tool(
    *, include_semantic_recall: bool = True
) -> ChatCompletionToolParam:
    """Create the unified memory tool definition."""
    description = _MEMORY_DESCRIPTION_BASE
    if include_semantic_recall:
        description += _MEMORY_RECALL_BLOCK
    action_enum = (
        ['working', 'persist', 'recall']
        if include_semantic_recall
        else [
            'working',
            'persist',
        ]
    )
    action_description = (
        'Memory operation: working (session state), persist (workspace facts), '
        'or recall (semantic search over indexed history).'
        if include_semantic_recall
        else 'Memory operation: working (session state) or persist (workspace facts).'
    )
    return create_tool_definition(
        name=MEMORY_TOOL_NAME,
        description=description,
        properties={
            'action': {
                'type': 'string',
                'enum': action_enum,
                'description': action_description,
            },
            'key': {
                'type': 'string',
                'description': (
                    'For persist: short identifier. For recall: natural-language search phrase.'
                ),
            },
            'kind': {
                'type': 'string',
                'enum': [
                    'convention',
                    'command',
                    'architecture',
                    'lesson',
                    'strategy',
                    'heuristic',
                    'decision',
                    'preference',
                ],
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


def create_search_history_tool() -> ChatCompletionToolParam:
    """Create the read-only search_history tool definition."""
    return create_tool_definition(
        name='search_history',
        description=(
            'Search earlier conversation and tool-event history when required '
            'information is no longer visible.'
        ),
        properties={
            'query': {
                'type': 'string',
                'description': 'Search query or keyword phrase.',
            },
            'max_results': {
                'type': 'integer',
                'description': 'Maximum number of results to return (default 8).',
                'minimum': 1,
                'maximum': 10,
            },
        },
        required=['query'],
    )


__all__ = ['create_memory_tool', 'create_memory_manager_tool', 'create_search_history_tool']
