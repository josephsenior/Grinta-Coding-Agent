"""``glob`` tool — list files that match a glob pattern.

Returns the paths of files under a directory whose name (or relative path)
matches the provided glob.  Uses ripgrep's ``--files`` fast path when
available and falls back to a pure-Python walker that respects the
workspace ignore spec.

For searching the *contents* of files (text/regex matches) use the
``grep`` tool instead.  For structural symbol discovery use ``find_symbols``.
"""

from __future__ import annotations

from typing import Any

from backend.core.tools.tool_names import GLOB_TOOL_NAME
from backend.engine.tools._search_helpers import (
    DEFAULT_SEARCH_HEAD_LIMIT,
    build_ripgrep_file_discovery_args,
    collect_python_target_files,
    format_python_file_listing,
    has_ripgrep,
    make_glob_observation,
    normalize_glob_pattern,
    paginate_line_output,
    path_exists_error,
    resolve_search_pagination,
    get_ripgrep_truncation_warning,
    run_ripgrep_command,
)
from backend.engine.tools.param_defs import create_tool_definition
from backend.ledger.action.search import GlobAction
from backend.ledger.observation import Observation

_GLOB_DESCRIPTION = """\
List files under a directory whose name (or relative path) matches a glob.

Use ``glob`` when you need to enumerate files — for example to find all
tests, all TypeScript files, or files with a particular extension.  Output
is a newline-separated list of file paths.

For searching the *contents* of files for a regex pattern, use the ``grep``
tool instead.  For structural symbol discovery use ``find_symbols``.
"""


def create_glob_tool() -> dict[Any, Any]:
    """Create the glob tool definition."""
    return create_tool_definition(  # type: ignore[no-any-return, return-value]
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
) -> GlobAction:
    """Build a runnable ``GlobAction`` from tool-call arguments."""
    resolved_offset, resolved_head_limit = resolve_search_pagination(
        head_limit,
        offset,
    )
    return GlobAction(
        pattern=normalize_glob_pattern(pattern or ''),
        path=path or '.',
        head_limit=resolved_head_limit,
        offset=resolved_offset,
    )


def _glob_failure(*, message: str, pattern: str, path: str) -> Observation:
    from backend.core.errors.structured_edit_errors import (
        build_search_error_observation,
    )

    return build_search_error_observation(
        tool='glob',
        message=message,
        pattern=pattern,
        path=path,
    )


def execute_glob(action: GlobAction) -> Observation:
    """List files matching ``action.pattern`` under ``action.path``."""
    path = action.path or '.'
    pattern = action.pattern or ''
    empty_message = 'No matching files found.'

    if not pattern:
        message = (
            'glob requires a non-empty `pattern` argument. '
            'Use the `grep` tool to search inside files.'
        )
        return _glob_failure(message=message, pattern=pattern, path=path)

    missing_path_error = path_exists_error(path)
    if missing_path_error is not None:
        return _glob_failure(message=missing_path_error, pattern=pattern, path=path)

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
            message = f'Error running ripgrep: {exc}'
            return _glob_failure(message=message, pattern=pattern, path=path)
        if getattr(result, 'timed_out', False):
            message = 'Search timed out after 30s'
            return _glob_failure(message=message, pattern=pattern, path=path)
        truncation_warning = get_ripgrep_truncation_warning(result)
        files = [line for line in result.stdout.splitlines() if line]
        content = paginate_line_output(
            files,
            offset=action.offset,
            head_limit=action.head_limit,
            empty_message=empty_message,
        )
        if truncation_warning:
            content = truncation_warning + '\n' + content
        return make_glob_observation(
            pattern=pattern,
            path=path,
            files=files,
            content=content,
        )

    target_files = collect_python_target_files(path, pattern)
    content = format_python_file_listing(
        target_files,
        offset=action.offset,
        head_limit=action.head_limit,
    )
    return make_glob_observation(
        pattern=pattern,
        path=path,
        files=target_files,
        content=content,
    )
