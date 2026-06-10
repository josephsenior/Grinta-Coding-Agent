"""``glob`` tool — list files that match a glob pattern.

Returns the paths of files under a directory whose name (or relative path)
matches the provided glob.  Uses ripgrep's ``--files`` fast path when
available and falls back to a pure-Python walker that respects the
workspace ignore spec.

For searching the *contents* of files (text/regex matches) use the
``grep`` tool instead.  For structural symbol discovery use ``find_symbols``.
"""

from __future__ import annotations

from backend.engine.tools._search_helpers import (
    DEFAULT_SEARCH_HEAD_LIMIT,
    build_ripgrep_file_discovery_args,
    collect_python_target_files,
    format_python_file_listing,
    has_ripgrep,
    normalize_glob_pattern,
    paginate_line_output,
    path_exists_or_error,
    resolve_search_pagination,
    run_ripgrep_command,
    search_error_action,
    search_results_action,
)
from backend.engine.tools.common import create_tool_definition
from backend.ledger.action import AgentThinkAction

from backend.inference.tool_names import GLOB_TOOL_NAME

_GLOB_DESCRIPTION = """\
List files under a directory whose name (or relative path) matches a glob.

Use ``glob`` when you need to enumerate files — for example to find all
tests, all TypeScript files, or files with a particular extension.  Output
is a newline-separated list of file paths.

For searching the *contents* of files for a regex pattern, use the ``grep``
tool instead.  For structural symbol discovery use ``find_symbols``.
"""


def create_glob_tool() -> dict:
    """Create the glob tool definition."""
    return create_tool_definition(  # type: ignore[no-any-return]
        name=GLOB_TOOL_NAME,
        description=_GLOB_DESCRIPTION,
        properties={
            'pattern': {
                'type': 'string',
                'description': (
                    "Glob to match, e.g. '*.ts', 'src/**/*.test.js', "
                    "or '**/conftest.py'."
                ),
            },
            'path': {
                'type': 'string',
                'description': (
                    'Directory to search in. '
                    'Defaults to the current workspace directory.'
                ),
            },
            'head_limit': {
                'type': 'integer',
                'description': (
                    'Limit output to the first N file paths after offset '
                    f'(default: {DEFAULT_SEARCH_HEAD_LIMIT}). Pass 0 for unlimited.'
                ),
            },
            'offset': {
                'type': 'integer',
                'description': (
                    'Skip the first N file paths before applying head_limit '
                    '(default: 0).'
                ),
            },
        },
        required=['pattern'],
    )


def build_glob_action(
    pattern: str = '',
    path: str = '.',
    head_limit: int | None = None,
    offset: int = 0,
) -> AgentThinkAction:
    """List files that match ``pattern`` under ``path``."""
    path = path or '.'
    pattern = normalize_glob_pattern(pattern or '')
    resolved_offset, resolved_head_limit = resolve_search_pagination(
        head_limit,
        offset,
    )

    if not pattern:
        return _invalid_glob_arguments_action()

    missing_path_error = path_exists_or_error(
        path, source_tool=GLOB_TOOL_NAME
    )
    if missing_path_error is not None:
        return missing_path_error

    empty_message = 'No matching files found.'
    rg_path = has_ripgrep()
    if rg_path:
        try:
            result = run_ripgrep_command(
                build_ripgrep_file_discovery_args(
                    rg_path,
                    file_pattern=pattern,
                    path=path,
                )
            )
        except Exception as exc:
            return search_error_action(
                f'Error running ripgrep: {exc}', source_tool=GLOB_TOOL_NAME
            )
        if getattr(result, 'timed_out', False):
            return search_error_action(
                'Search timed out after 30s',
                source_tool=GLOB_TOOL_NAME,
            )
        lines = result.stdout.splitlines()
        return search_results_action(
            paginate_line_output(
                lines,
                offset=resolved_offset,
                head_limit=resolved_head_limit,
                empty_message=empty_message,
            ),
            source_tool=GLOB_TOOL_NAME,
        )

    target_files = collect_python_target_files(path, pattern)
    return search_results_action(
        format_python_file_listing(
            target_files,
            offset=resolved_offset,
            head_limit=resolved_head_limit,
        ),
        source_tool=GLOB_TOOL_NAME,
    )


def _invalid_glob_arguments_action() -> AgentThinkAction:
    return search_error_action(
        'glob requires a non-empty `pattern` argument. Use the `grep` tool to search inside files.',
        source_tool=GLOB_TOOL_NAME,
    )
