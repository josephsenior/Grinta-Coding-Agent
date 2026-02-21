"""Tools for exploring repository structure and entity contents."""

from __future__ import annotations

from backend.engines.orchestrator.tools.common import create_tool_definition

_EXPLORE_TREE_STRUCTURE_DESCRIPTION = """
Unified repository exploring tool that traverses a pre-built code graph to retrieve dependency structure around specified entities.
The search can be controlled to traverse upstream (exploring dependencies that entities rely on) or downstream (exploring how entities impact others), with optional limits on traversal depth and filters for entity and dependency types.

Code Graph Definition:
* Entity Types: 'directory', 'file', 'class', 'function'.
* Dependency Types: 'contains', 'imports', 'invokes', 'inherits'.
* Hierarchy:
    - Directories contain files and subdirectories.
    - Files contain classes and functions.
    - Classes contain inner classes and methods.
    - Functions can contain inner functions.
* Interactions:
    - Files/classes/functions can import classes and functions.
    - Classes can inherit from other classes.
    - Classes and functions can invoke others.

Entity ID:
* Unique identifier including file path and module path.
* Example: "interface/C.py:C.method_a.inner_func" identifies function `inner_func` within `method_a` of class `C` in "interface/C.py".

Example Usage:
1. Exploring Downstream Dependencies:
    explore_tree_structure(
        start_entities=['src/module_a.py:ClassA'],
        direction='downstream',
        traversal_depth=2,
        dependency_type_filter=['invokes', 'imports']
    )
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

_GET_ENTITY_CONTENTS_DESCRIPTION = """
Searches the codebase to retrieve the complete implementations of specified entities based on the provided entity names.
The tool can handle specific entity queries such as function names, class names, or file paths.

Usage Example:
# Search for a specific function implementation
get_entity_contents(['src/my_file.py:MyClass.func_name'])

# Search for a file's complete content
get_entity_contents(['src/my_file.py'])

Entity Name Format:
- To specify a function or class, use the format: `file_path:QualifiedName` (e.g., 'src/helpers/math_helpers.py:MathUtils.calculate_sum').
- To search for a file's content, use only the file path (e.g., 'src/my_file.py').
"""

def create_get_entity_contents_tool():
    """Create the get_entity_contents tool definition."""
    return create_tool_definition(
        name="get_entity_contents",
        description=_GET_ENTITY_CONTENTS_DESCRIPTION,
        properties={
            "entity_names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "A list of entity names to query. Format: 'file_path:QualifiedName' or 'file_path'.",
            },
        },
        required=["entity_names"],
    )
