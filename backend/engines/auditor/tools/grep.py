"""Read-only grep tool definition for regex-based content search."""

from backend.engines.auditor.tools.common import (
    create_tool_definition,
    get_common_path_param,
    get_common_pattern_param,
)

_GREP_DESCRIPTION = (
    "Fast content search tool.\n"
    "* Searches file contents using regular expressions\n"
    '* Supports full regex syntax (eg. "log.*Error", "function\\s+\\w+", etc.)\n'
    '* Filter files by pattern with the include parameter (eg. "*.js", '
    '"*.{ts,tsx}")\n'
    "* Returns matching file paths sorted by modification time.\n"
    "* Only the first 100 results are returned. Consider narrowing your search "
    "with stricter regex patterns or provide path parameter if you need more "
    "results.\n"
    "* Use this tool when you need to find files containing specific patterns\n"
    "* When you are doing an open ended search that may require multiple rounds "
    "of globbing and grepping, use the Agent tool instead\n"
)


def create_grep_tool():
    """Create the grep tool for the read-only agent."""
    return create_tool_definition(
        name="grep",
        description=_GREP_DESCRIPTION,
        properties={
            "pattern": get_common_pattern_param(
                "The regex pattern to search for in file contents"
            ),
            "path": get_common_path_param(),
            "include": {
                "type": "string",
                "description": 'Optional file pattern to filter which files to search (e.g., "*.js", "*.{ts,tsx}")',
            },
        },
        required=["pattern"],
    )


GREP_TOOL = create_grep_tool()
