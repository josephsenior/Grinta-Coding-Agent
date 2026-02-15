"""Tools for fetching entity contents and searching repository snippets."""

from backend.llm.tool_types import make_function_chunk, make_tool_param

_SEARCH_ENTITY_DESCRIPTION = "\nSearches the codebase to retrieve the complete implementations of specified entities based on the provided entity names.\nThe tool can handle specific entity queries such as function names, class names, or file paths.\n\n**Usage Example:**\n# Search for a specific function implementation\nget_entity_contents(['src/my_file.py:MyClass.func_name'])\n\n# Search for a file's complete content\nget_entity_contents(['src/my_file.py'])\n\n**Entity Name Format:**\n- To specify a function or class, use the format: `file_path:QualifiedName`\n  (e.g., 'src/helpers/math_helpers.py:MathUtils.calculate_sum').\n- To search for a file's content, use only the file path (e.g., 'src/my_file.py').\n"
SearchEntityTool = make_tool_param(
    type="function",
    function=make_function_chunk(
        name="get_entity_contents",
        description=_SEARCH_ENTITY_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "entity_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "A list of entity names to query. Each entity name can represent a function, class, or file. For functions or classes, the format should be 'file_path:QualifiedName' (e.g., 'src/helpers/math_helpers.py:MathUtils.calculate_sum'). For files, use just the file path (e.g., 'src/my_file.py').",
                },
            },
            "required": ["entity_names"],
        },
    ),
)
_SEARCH_REPO_DESCRIPTION = 'Searches the codebase to retrieve relevant code snippets based on given queries(terms or line numbers).\n** Note:\n- Either `search_terms` or `line_nums` must be provided to perform a search.\n- If `search_terms` are provided, it searches for code snippets based on each term:\n- If `line_nums` is provided, it searches for code snippets around the specified lines within the file defined by `file_path_or_pattern`.\n\n** Example Usage:\n# Search for code content contain keyword `order`, `bill`\nsearch_code_snippets(search_terms=["order", "bill"])\n\n# Search for a class\nsearch_code_snippets(search_terms=["MyClass"])\n\n# Search for context around specific lines (10 and 15) within a file\nsearch_code_snippets(line_nums=[10, 15], file_path_or_pattern=\'src/example.py\')\n'
SearchRepoTool = make_tool_param(
    type="function",
    function=make_function_chunk(
        name="search_code_snippets",
        description=_SEARCH_REPO_DESCRIPTION,
        parameters={
            "type": "object",
            "properties": {
                "search_terms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "A list of names, keywords, or code snippets to search for within the codebase. This can include potential function names, class names, or general code fragments. Either `search_terms` or `line_nums` must be provided to perform a search.",
                },
                "line_nums": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Specific line numbers to locate code snippets within a specified file. Must be used alongside a valid `file_path_or_pattern`. Either `line_nums` or `search_terms` must be provided to perform a search.",
                },
                "file_path_or_pattern": {
                    "type": "string",
                    "description": 'A glob pattern or specific file path used to filter search results to particular files or directories. Defaults to "**/*.py", meaning all Python files are searched by default. If `line_nums` are provided, this must specify a specific file path.',
                    "default": "**/*.py",
                },
            },
            "required": [],
        },
    ),
)
