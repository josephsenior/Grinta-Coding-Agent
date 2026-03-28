from __future__ import annotations

from backend.engine.tools.common import create_tool_definition

MEMORY_MANAGER_TOOL_NAME = "memory_manager"

def create_memory_manager_tool():
    return create_tool_definition(
        name=MEMORY_MANAGER_TOOL_NAME,
        description=(
            "Manage both structured working memory and long-term narrative memory. "
            "Use 'semantic_recall' to perform a fuzzy search across indexed conversation memory, "
            "or 'working_memory' to maintain a structured cognitive workspace "
            "that survives context condensation (sections: hypothesis, findings, blockers, "
            "file_context, decisions, plan)."
        ),
        properties={
            "action": {
                "type": "string",
                "enum": ["semantic_recall", "working_memory"],
                "description": (
                    "The type of memory operation to execute:\n"
                    "- 'semantic_recall': Perform a fuzzy/vector search across indexed conversation history using a natural language phrase.\n"
                    "- 'working_memory': Manage structured cognitive state (hypothesis, findings, blockers, file_context, decisions, plan)."
                )
            },
            "key": {
                "type": "string",
                "description": "The search phrase for 'semantic_recall'."
            },
            "update_type": {
                "type": "string",
                "enum": ["update", "get", "clear_section"],
                "description": "Type of update (Required for 'working_memory' action)."
            },
            "section": {
                "type": "string",
                "enum": ["hypothesis", "findings", "blockers", "file_context", "decisions", "plan", "all"],
                "description": "The section to operate on (Required for 'working_memory' action)."
            },
            "content": {
                "type": "string",
                "description": "The structural content to store (Required for 'working_memory' action 'update')."
            }
        },
        required=["action"]
    )
