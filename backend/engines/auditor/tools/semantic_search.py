"""Semantic Search Tool - Find Code by Meaning.

Search codebase by semantic meaning, not just text patterns.
Better than grep for conceptual searches.
"""

from backend.llm.tool_types import make_function_chunk, make_tool_param

_SEMANTIC_SEARCH_DESCRIPTION = """Semantic code search - Find code by meaning, not just keywords

Searches codebase using semantic similarity to find relevant code.

WHEN TO USE:
- "Find authentication logic" (not just grep "auth")
- "Where is error handling?" (finds try/except, error checks, etc.)
- "Show me database queries" (finds SQL, ORM, etc.)
- "Find validation code" (finds validators, schema checks)

WHEN NOT TO USE:
- Exact string matching → use grep instead
- Filename search → use glob instead
- Known symbol names → use ultimate_explorer instead

EXAMPLES:

Good queries:
- "How is user authentication implemented?"
- "Where do we handle API rate limiting?"
- "Find all database migration files"
- "Show me payment processing logic"

Bad queries (use grep instead):
- "API_KEY" (exact string → use grep)
- "UserAuth" (symbol name → use ultimate_explorer)
- "*.test.js" (filename → use glob)

Returns:
- Relevant code snippets with file paths
- Similarity scores
- Context around matches
"""


def create_semantic_search_tool():
    """Create Semantic Search tool for Auditor.

    Returns:
        ChatCompletionToolParam for semantic code search

    """
    return make_tool_param(
        type="function",
        function=make_function_chunk(
            name="semantic_search",
            description=_SEMANTIC_SEARCH_DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "description": "Semantic query describing what you're looking for (natural language)",
                        "type": "string",
                    },
                    "file_types": {
                        "description": "Optional file type filter (e.g., '.py', '.js', '.java')",
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "max_results": {
                        "description": "Maximum number of results to return (default: 10)",
                        "type": "integer",
                        "default": 10,
                    },
                    "min_similarity": {
                        "description": "Minimum similarity score (0.0-1.0, default: 0.7)",
                        "type": "number",
                        "default": 0.7,
                    },
                },
                "required": ["query"],
            },
        ),
    )
