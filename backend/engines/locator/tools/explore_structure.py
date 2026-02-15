"""Tool definitions for exploring repository structure in LoCAgent."""

from backend.llm.tool_types import make_function_chunk, make_tool_param

_SIMPLIFIED_STRUCTURE_EXPLORER_DESCRIPTION = "\nA unified tool that traverses a pre-built code graph to retrieve dependency structure around specified entities,\nwith options to explore upstream or downstream, and control traversal depth and filters for entity and dependency types.\n"
_SIMPLIFIED_TREE_EXAMPLE = "\nExample Usage:\n1. Exploring Downstream Dependencies:\n    ```\n    explore_tree_structure(\n        start_entities=['src/module_a.py:ClassA'],\n        direction='downstream',\n        traversal_depth=2,\n        dependency_type_filter=['invokes', 'imports']\n    )\n    ```\n2. Exploring the repository structure from the root directory (/) up to two levels deep:\n    ```\n    explore_tree_structure(\n      start_entities=['/'],\n      traversal_depth=2,\n      dependency_type_filter=['contains']\n    )\n    ```\n3. Generate Class Diagrams:\n    ```\n    explore_tree_structure(\n        start_entities=selected_entity_ids,\n        direction='both',\n        traverse_depth=-1,\n        dependency_type_filter=['inherits']\n    )\n    ```\n"
_DETAILED_STRUCTURE_EXPLORER_DESCRIPTION = "\nUnified repository exploring tool that traverses a pre-built code graph to retrieve dependency structure around specified entities.\nThe search can be controlled to traverse upstream (exploring dependencies that entities rely on) or downstream (exploring how entities impact others), with optional limits on traversal depth and filters for entity and dependency types.\n\nCode Graph Definition:\n* Entity Types: 'directory', 'file', 'class', 'function'.\n* Dependency Types: 'contains', 'imports', 'invokes', 'inherits'.\n* Hierarchy:\n    - Directories contain files and subdirectories.\n    - Files contain classes and functions.\n    - Classes contain inner classes and methods.\n    - Functions can contain inner functions.\n* Interactions:\n    - Files/classes/functions can import classes and functions.\n    - Classes can inherit from other classes.\n    - Classes and functions can invoke others (invocations in a class's `__init__` are attributed to the class).\nEntity ID:\n* Unique identifier including file path and module path.\n* Here's an example of an Entity ID: `\"interface/C.py:C.method_a.inner_func\"` identifies function `inner_func` within `method_a` of class `C` in `\"interface/C.py\"`.\n\nNotes:\n* Traversal Control: The `traversal_depth` parameter specifies how deep the function should explore the graph starting from the input entities.\n* Filtering: Use `entity_type_filter` and `dependency_type_filter` to narrow down the scope of the search, focusing on specific entity types and relationships.\n\n"
_DETAILED_TREE_EXAMPLE = "\nExample Usage:\n1. Exploring Outward Dependencies:\n    ```\n    explore_tree_structure(\n        start_entities=['src/module_a.py:ClassA'],\n        direction='downstream',\n        traversal_depth=2,\n        dependency_type_filter=['invokes', 'imports']\n    )\n    ```\n    This retrieves the dependencies of `ClassA` up to 2 levels deep, focusing only on classes and functions with 'invokes' and 'imports' relationships.\n\n2. Exploring Inward Dependencies:\n    ```\n    explore_tree_structure(\n        start_entities=['src/module_b.py:FunctionY'],\n        direction='upstream',\n        traversal_depth=-1\n    )\n    ```\n    This finds all entities that depend on `FunctionY` without restricting the traversal depth.\n3. Exploring Repository Structure:\n    ```\n    explore_tree_structure(\n      start_entities=['/'],\n      traversal_depth=2,\n      dependency_type_filter=['contains']\n    )\n    ```\n    This retrieves the tree repository structure from the root directory (/), traversing up to two levels deep and focusing only on 'contains' relationship.\n4. Generate Class Diagrams:\n    ```\n    explore_tree_structure(\n        start_entities=selected_entity_ids,\n        direction='both',\n        traverse_depth=-1,\n        dependency_type_filter=['inherits']\n    )\n    ```\n"
_STRUCTURE_EXPLORER_PARAMETERS = {
    "type": "object",
    "properties": {
        "start_entities": {
            "description": 'List of entities (e.g., class, function, file, or directory paths) to begin the search from.\nEntities representing classes or functions must be formatted as "file_path:QualifiedName" (e.g., `interface/C.py:C.method_a.inner_func`).\nFor files or directories, provide only the file or directory path (e.g., `src/module_a.py` or `src/`).',
            "type": "array",
            "items": {"type": "string"},
        },
        "direction": {
            "description": "Direction of traversal in the code graph; allowed options are: `upstream`, `downstream`, `both`.\n- 'upstream': Traversal to explore dependencies that the specified entities rely on (how they depend on others).\n- 'downstream': Traversal to explore the effects or interactions of the specified entities on others (how others depend on them).\n- 'both': Traversal on both direction.",
            "type": "string",
            "enum": ["upstream", "downstream", "both"],
            "default": "downstream",
        },
        "traversal_depth": {
            "description": "Maximum depth of traversal. A value of -1 indicates unlimited depth (subject to a maximum limit).Must be either `-1` or a non-negative integer (≥ 0).",
            "type": "integer",
            "default": 2,
        },
        "entity_type_filter": {
            "description": "List of entity types (e.g., 'class', 'function', 'file', 'directory') to include in the traversal. If None, all entity types are included.",
            "type": ["array", "null"],
            "items": {"type": "string"},
            "default": None,
        },
        "dependency_type_filter": {
            "description": "List of dependency types (e.g., 'contains', 'imports', 'invokes', 'inherits') to include in the traversal. If None, all dependency types are included.",
            "type": ["array", "null"],
            "items": {"type": "string"},
            "default": None,
        },
    },
    "required": ["start_entities"],
}


def create_explore_tree_structure_tool(
    use_simplified_description: bool = False,
):
    """Create tree structure exploration tool for function calling.

    Builds a tool definition for exploring code structure with either simplified
    or detailed descriptions based on the agent's needs.

    Args:
        use_simplified_description: If True, use simplified description; otherwise detailed

    Returns:
        Chat completion tool parameter for tree structure exploration

    """
    description = (
        _SIMPLIFIED_STRUCTURE_EXPLORER_DESCRIPTION
        if use_simplified_description
        else _DETAILED_STRUCTURE_EXPLORER_DESCRIPTION
    )
    example = (
        _SIMPLIFIED_TREE_EXAMPLE
        if use_simplified_description
        else _DETAILED_TREE_EXAMPLE
    )
    return make_tool_param(
        type="function",
        function=make_function_chunk(
            name="explore_tree_structure",
            description=description + example,
            parameters=_STRUCTURE_EXPLORER_PARAMETERS,
        ),
    )
