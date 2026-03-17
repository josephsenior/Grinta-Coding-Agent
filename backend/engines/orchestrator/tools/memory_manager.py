from typing import Any
from backend.engines.orchestrator.tools.common import create_tool_definition

MEMORY_MANAGER_TOOL_NAME = "memory_manager"

def create_memory_manager_tool() -> dict[str, Any]:
    return create_tool_definition(
        name=MEMORY_MANAGER_TOOL_NAME,
        description=(
            "Manage both structured working memory and long-term narrative memory. "
            "Use 'note' to save flat key-value insights, 'recall'/'semantic_recall' "
            "to fetch them, or 'working_memory' to maintain a structured cognitive workspace "
            "that survives context condensation (sections: hypothesis, findings, blockers, "
            "file_context, decisions, plan)."
        ),
        properties={
            "action": {
                "type": "string",
                "enum": ["note", "recall", "semantic_recall", "working_memory"],
                "description": (
                    "The type of memory operation to execute:\n"
                    "- 'note': Store a key-value pair in your local scratchpad.\n"
                    "- 'recall': Fetch an EXACT key previously saved via 'note'.\n"
                    "- 'semantic_recall': Perform a fuzzy/vector search across broad or long-term history using a natural language phrase.\n"
                    "- 'working_memory': Manage structured cognitive state (hypothesis, blockers, etc.)."
                )
            },
            "key": {
                "type": "string",
                "description": "The key to store/retrieve for 'note'/'recall', or search phrase for 'semantic_recall'."
            },
            "value": {
                "type": "string",
                "description": "The text to store when using 'note'."
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
