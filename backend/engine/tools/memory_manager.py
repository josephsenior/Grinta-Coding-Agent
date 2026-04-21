from __future__ import annotations

from backend.engine.tools.common import create_tool_definition

MEMORY_MANAGER_TOOL_NAME = 'memory_manager'


def create_memory_manager_tool():
    return create_tool_definition(
        name=MEMORY_MANAGER_TOOL_NAME,
        description=(
            'Session-scoped memory. Two actions:\n'
            "- 'working_memory': structured cognitive state for the CURRENT session "
            '(sections: hypothesis, findings, blockers, file_context, decisions, plan). '
            'Survives context condensation, but NOT session restart.\n'
            "- 'semantic_recall': fuzzy/vector search across this session's indexed "
            'conversation history when the visible window no longer shows what you need.\n\n'
            'Do NOT confuse with `note`/`recall` — those are a FLAT KEY-VALUE '
            'SCRATCHPAD that persists ACROSS sessions (workspace-level). Rule of thumb: '
            'short-term + structured → memory_manager; long-term + simple key-value → note/recall.'
        ),
        properties={
            'action': {
                'type': 'string',
                'enum': ['semantic_recall', 'working_memory'],
                'description': (
                    'The type of memory operation to execute:\n'
                    "- 'semantic_recall': Perform a fuzzy/vector search across indexed conversation history using a natural language phrase.\n"
                    "- 'working_memory': Manage structured cognitive state (hypothesis, findings, blockers, file_context, decisions, plan)."
                ),
            },
            'key': {
                'type': 'string',
                'description': "The search phrase for 'semantic_recall'.",
            },
            'update_type': {
                'type': 'string',
                'enum': ['update', 'get', 'clear_section'],
                'description': "Type of update (Required for 'working_memory' action).",
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
                'description': "The section to operate on (Required for 'working_memory' action).",
            },
            'content': {
                'type': 'string',
                'description': "The structural content to store (Required for 'working_memory' action 'update').",
            },
        },
        required=['action'],
    )
