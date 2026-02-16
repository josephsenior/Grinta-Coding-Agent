"""Read-only glob tool definition for path discovery."""

from backend.engines.auditor.tools.common import (
    create_tool_definition,
    get_common_path_param,
    get_common_pattern_param,
)

_GLOB_DESCRIPTION = (
    "Fast file pattern matching tool.\n"
    '* Supports glob patterns like "**/*.js" or "src/**/*.ts"\n'
    "* Use this tool when you need to find files by name patterns\n"
    "* Returns matching file paths sorted by modification time\n"
    "* Only the first 100 results are returned. Consider narrowing your search "
    "with stricter glob patterns or provide path parameter if you need more "
    "results.\n"
    "* When you are doing an open ended search that may require multiple rounds "
    "of globbing and grepping, use the Agent tool instead\n"
)


def create_glob_tool():
    """Create the glob tool for the read-only agent."""
    return create_tool_definition(
        name="glob",
        description=_GLOB_DESCRIPTION,
        properties={
            "pattern": get_common_pattern_param(
                'The glob pattern to match files (e.g., "**/*.js", "src/**/*.ts")'
            ),
            "path": get_common_path_param(),
        },
        required=["pattern"],
    )


GlobTool = create_glob_tool()
