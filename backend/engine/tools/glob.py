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
    build_ripgrep_file_discovery_args,
    collect_python_target_files,
    format_python_file_listing,
    format_ripgrep_output,
    has_ripgrep,
    normalize_glob_pattern,
    path_exists_or_error,
    run_ripgrep_with_handler,
    search_error_action,
    search_results_action,
)
from backend.engine.tools.common import create_tool_definition
from backend.ledger.action import AgentThinkAction

GLOB_TOOL_NAME = 'glob'

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
            'max_results': {
                'type': 'integer',
                'description': (
                    'Maximum number of files to return '
                    '(default: 100, max: 1000).'
                ),
            },
        },
        required=['pattern'],
    )


def build_glob_action(
    pattern: str = '',
    path: str = '.',
    max_results: int = 100,
) -> AgentThinkAction:
    """List files that match ``pattern`` under ``path``."""
    path = path or '.'
    max_results = max(1, min(int(max_results), 1000))
    pattern = normalize_glob_pattern(pattern or '')

    if not pattern:
        return _invalid_glob_arguments_action()

    missing_path_error = path_exists_or_error(
        path, source_tool=GLOB_TOOL_NAME
    )
    if missing_path_error is not None:
        return missing_path_error

    rg_path = has_ripgrep()
    if rg_path:
        return run_ripgrep_with_handler(
            lambda: build_ripgrep_file_discovery_args(
                rg_path,
                file_pattern=pattern,
                path=path,
            ),
            max_lines=max_results,
            empty_message='No matching files found.',
            source_tool=GLOB_TOOL_NAME,
        )

    target_files = collect_python_target_files(path, pattern)
    return search_results_action(
        format_python_file_listing(target_files, max_results=max_results),
        source_tool=GLOB_TOOL_NAME,
    )


def _invalid_glob_arguments_action() -> AgentThinkAction:
    return search_error_action(
        'glob requires a non-empty `pattern` argument. Use the `grep` tool to search inside files.',
        source_tool=GLOB_TOOL_NAME,
    )
