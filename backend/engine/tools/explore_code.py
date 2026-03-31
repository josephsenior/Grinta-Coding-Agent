"""Tools for exploring repository structure and entity contents."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.ledger.action import AgentThinkAction

from backend.engine.tools.common import create_tool_definition

_EXPLORE_TREE_STRUCTURE_DESCRIPTION = """
Traverse a pre-built code graph to explore dependencies around entities.
Direction: upstream (what it depends on), downstream (what depends on it), or both.
Entity types: directory, file, class, function. Dependency types: contains, imports, invokes, inherits.
Entity ID format: 'path/file.py:Class.method' (e.g. 'src/api.py:UserAPI.get_user').
For text search use `search_code`; for precise refs at known positions use `lsp_query`.
"""

def create_explore_tree_structure_tool():
    """Create the explore_tree_structure tool definition."""
    return create_tool_definition(
        name="explore_tree_structure",
        description=_EXPLORE_TREE_STRUCTURE_DESCRIPTION,
        properties={
            "start_entities": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of entity IDs to start from (e.g., ['src/api.py:UserAPI']).",
            },
            "direction": {
                "type": "string",
                "enum": ["upstream", "downstream", "both"],
                "description": "Direction to traverse the graph (default: 'downstream').",
            },
            "traversal_depth": {
                "type": "integer",
                "description": "Maximum depth to traverse (-1 for unlimited, default: 2).",
            },
            "entity_type_filter": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Filter by entity types (e.g., ['class', 'function']).",
            },
            "dependency_type_filter": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Filter by dependency types (e.g., ['imports', 'invokes']).",
            },
        },
        required=["start_entities"],
    )

_READ_SYMBOL_DEFINITION_DESCRIPTION = """
Retrieve the full implementation of a symbol or file from the code graph.
Format: 'path/file.py:Class.method' for symbols, or just 'path/file.py' for full file contents.
For text search use `search_code`; for refs at known positions use `lsp_query`.
"""

def create_read_symbol_definition_tool():
    """Create the read_symbol_definition tool definition."""
    return create_tool_definition(
        name="read_symbol_definition",
        description=_READ_SYMBOL_DEFINITION_DESCRIPTION,
        properties={
            "entity_names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "A list of entity names to query. Format: 'path:QualifiedName' or 'path'.",
            },
        },
        required=["entity_names"],
    )

def build_explore_tree_structure_action(arguments: dict) -> "AgentThinkAction":
    """Build action for explore_tree_structure tool."""
    from backend.ledger.action import AgentThinkAction
    from backend.execution.plugins.agent_skills.repo_ops.explorer import explore_tree_structure
    import json

    start_entities = arguments.get("start_entities", [])
    direction = arguments.get("direction", "downstream")
    traversal_depth = arguments.get("traversal_depth", 2)
    entity_type_filter = arguments.get("entity_type_filter")
    dependency_type_filter = arguments.get("dependency_type_filter")

    try:
        result = explore_tree_structure(
            start_entities=start_entities,
            direction=direction,
            traversal_depth=traversal_depth,
            entity_type_filter=entity_type_filter,
            dependency_type_filter=dependency_type_filter,
        )
        return AgentThinkAction(thought=f"[EXPLORE_TREE_STRUCTURE]\n{json.dumps(result, indent=2)}")
    except Exception as e:
        return AgentThinkAction(thought=f"[EXPLORE_TREE_STRUCTURE] Error: {e}")

def build_read_symbol_definition_action(arguments: dict) -> "AgentThinkAction":
    """Build action for read_symbol_definition tool."""
    from backend.ledger.action import AgentThinkAction
    from backend.execution.plugins.agent_skills.repo_ops.explorer import get_entity_contents
    import json

    entity_names = arguments.get("entity_names", [])

    try:
        result = get_entity_contents(entity_names=entity_names)
        return AgentThinkAction(thought=f"[READ_SYMBOL_DEFINITION]\n{json.dumps(result, indent=2)}")
    except Exception as e:
        return AgentThinkAction(thought=f"[READ_SYMBOL_DEFINITION] Error: {e}")
