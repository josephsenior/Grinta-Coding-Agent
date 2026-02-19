"""Read-only view tool definition for inspecting files and directories."""

from backend.engines.auditor.tools.common import create_tool_definition

_VIEW_DESCRIPTION = (
    "Reads a file or list directories from the local filesystem.\n"
    "* The path parameter must be an absolute path, not a relative path.\n"
    "* If `path` is a file, `view` displays the result of applying `cat -n`; "
    "if `path` is a directory, `view` lists non-hidden files and directories "
    "up to 2 levels deep.\n"
    "* You can optionally specify a line range to view (especially handy for long "
    "files), but it's recommended to read the whole file by not providing this "
    "parameter.\n"
    "* For image files, the tool will display the image for you.\n"
    "* For large files that exceed the display limit:\n"
    "  - The output will be truncated and marked with `<response clipped>`\n"
    "  - Use the `view_range` parameter to view specific sections after the "
    "truncation point\n"
)


def create_view_tool():
    """Create the view tool for the read-only agent."""
    return create_tool_definition(
        name="view",
        description=_VIEW_DESCRIPTION,
        properties={
            "path": {
                "type": "string",
                "description": "The absolute path to the file to read or directory to list",
            },
            "view_range": {
                "description": (
                    "Optional parameter of `view` command when `path` points to a *file*. "
                    "If none is given, the full file is shown. If provided, the file will "
                    "be shown in the indicated line number range, e.g. [11, 12] will show "
                    "lines 11 and 12. Indexing at 1 to start. Setting `[start_line, -1]` "
                    "shows all lines from `start_line` to the end of the file."
                ),
                "items": {"type": "integer"},
                "type": "array",
            },
        },
        required=["path"],
    )


VIEW_TOOL = create_view_tool()
