"""``grep`` tool — regex/text search across project files.

Searches for a regex pattern inside files under a directory, using ripgrep
when available and falling back to a pure-Python walker that respects the
workspace ignore spec.

For file discovery (listing files matching a glob without scanning their
contents) use the ``glob`` tool instead.
"""

from __future__ import annotations

import os
from typing import Any

from backend.engine.tools._search_helpers import (
    DEFAULT_GREP_OUTPUT_MODE,
    DEFAULT_SEARCH_HEAD_LIMIT,
    GREP_OUTPUT_MODES,
    build_ripgrep_count_args,
    build_ripgrep_files_with_matches_args,
    build_ripgrep_text_search_args,
    collect_python_files_with_matches,
    collect_python_match_counts,
    collect_python_match_results,
    collect_python_target_files,
    compile_search_regex,
    has_ripgrep,
    make_grep_observation,
    paginate_line_output,
    resolve_search_pagination,
    run_ripgrep_command,
)
from backend.engine.tools.common import create_tool_definition
from backend.inference.tool_names import GREP_TOOL_NAME
from backend.ledger.action.search import GrepAction
from backend.ledger.observation import Observation
from backend.ledger.observation.search import GrepObservation

_GREP_DESCRIPTION = """\
Search the project for a regex pattern inside file contents.

Use ``grep`` for text/regex search. Prefer ``output_mode=files_with_matches``
first to orient quickly; switch to ``content`` when you need matching lines.

Output modes:
- ``files_with_matches`` — file paths only (default; lowest token cost)
- ``content`` — ripgrep-style ``path:line:content`` with optional context
- ``count`` — ``path:match_count`` per file

For listing files by name pattern (without reading contents), use ``glob``.
For symbol-aware navigation use ``find_symbols`` or ``lsp``.
"""


def create_grep_tool() -> dict[Any, Any]:
    """Create the grep tool definition."""
    return create_tool_definition(  # type: ignore[no-any-return, return-value]
        name=GREP_TOOL_NAME,
        description=_GREP_DESCRIPTION,
        properties={
            'pattern': {
                'type': 'string',
                'description': (
                    'Regex pattern to search for, e.g. '
                    "'function\\\\s+\\\\w+' or 'TODO'."
                ),
            },
            'path': {
                'type': 'string',
                'description': (
                    'Directory or file path to search in. '
                    'Defaults to the current workspace directory.'
                ),
            },
            'file_pattern': {
                'type': 'string',
                'description': (
                    'Optional glob to limit which files are searched '
                    "(e.g. '*.ts', 'src/**/*.test.js')."
                ),
            },
            'output_mode': {
                'type': 'string',
                'enum': ['content', 'files_with_matches', 'count'],
                'description': (
                    'Result shape: files_with_matches (default), content, or count.'
                ),
            },
            'context_lines': {
                'type': 'integer',
                'description': (
                    'Lines of context before/after each match in content mode '
                    '(default: 2, max: 10). Ignored in other modes.'
                ),
            },
            'case_sensitive': {
                'type': 'boolean',
                'description': 'Whether the search is case-sensitive (default: false).',
            },
            'head_limit': {
                'type': 'integer',
                'description': (
                    'Limit output to the first N lines/entries after offset '
                    f'(default: {DEFAULT_SEARCH_HEAD_LIMIT}). Pass 0 for unlimited.'
                ),
            },
            'offset': {
                'type': 'integer',
                'description': (
                    'Skip the first N output lines/entries before applying head_limit '
                    '(default: 0).'
                ),
            },
        },
        required=['pattern'],
    )


def build_grep_action(
    pattern: str = '',
    path: str = '.',
    file_pattern: str = '',
    output_mode: str = DEFAULT_GREP_OUTPUT_MODE,
    context_lines: int = 2,
    case_sensitive: bool | str = False,
    head_limit: int | None = None,
    offset: int = 0,
) -> GrepAction:
    """Build a runnable ``GrepAction`` from tool-call arguments."""
    resolved_offset, resolved_head_limit = resolve_search_pagination(
        head_limit,
        offset,
    )
    mode = (output_mode or DEFAULT_GREP_OUTPUT_MODE).strip().lower()
    if mode not in GREP_OUTPUT_MODES:
        mode = DEFAULT_GREP_OUTPUT_MODE
    is_case_sensitive = case_sensitive is True or str(case_sensitive).lower() == 'true'
    return GrepAction(
        pattern=pattern or '',
        path=path or '.',
        file_pattern=file_pattern or '',
        output_mode=mode,
        context_lines=max(0, min(int(context_lines), 10)),
        case_sensitive=is_case_sensitive,
        head_limit=resolved_head_limit,
        offset=resolved_offset,
    )


def _grep_failure(
    *,
    message: str,
    pattern: str,
    path: str,
    output_mode: str,
) -> Observation:
    from backend.execution.aes.structured_edit_errors import build_search_error_observation

    return build_search_error_observation(
        tool='grep',
        message=message,
        pattern=pattern,
        path=path,
        output_mode=output_mode,
    )


def execute_grep(action: GrepAction) -> Observation:
    """Execute a regex text search and return a structured observation."""
    pattern = action.pattern
    path = action.path or '.'
    file_pattern = action.file_pattern or ''
    mode = action.output_mode or DEFAULT_GREP_OUTPUT_MODE
    empty_message = 'No matches found.'

    if not pattern:
        message = (
            'grep requires a non-empty `pattern` argument. '
            'Use the `glob` tool to list files.'
        )
        return _grep_failure(
            message=message,
            pattern=pattern,
            path=path,
            output_mode=mode,
        )

    regex, regex_error = compile_search_regex(
        pattern,
        is_case_sensitive=action.case_sensitive,
        invalid_hint=(
            "Invalid regex in 'pattern' for grep: {exc}. "
            'Note: glob patterns (e.g. *.ts) belong to the `glob` tool, not `grep`.'
        ),
    )
    if regex_error is not None:
        return _grep_failure(
            message=regex_error,
            pattern=pattern,
            path=path,
            output_mode=mode,
        )

    if not os.path.exists(path):
        message = f'Path does not exist: {path}'
        return _grep_failure(
            message=message,
            pattern=pattern,
            path=path,
            output_mode=mode,
        )

    rg_path = has_ripgrep()
    if rg_path:
        return _run_ripgrep_mode(
            rg_path,
            action=action,
            pattern=pattern,
            path=path,
            file_pattern=file_pattern,
            output_mode=mode,
            regex=regex,
            empty_message=empty_message,
        )

    return _run_python_mode(
        action=action,
        path=path,
        file_pattern=file_pattern,
        output_mode=mode,
        regex=regex,
        empty_message=empty_message,
    )


def _run_ripgrep_mode(
    rg_path: str,
    *,
    action: GrepAction,
    pattern: str,
    path: str,
    file_pattern: str,
    output_mode: str,
    regex: object,
    empty_message: str,
) -> GrepObservation | Observation:
    if output_mode == 'files_with_matches':
        args = build_ripgrep_files_with_matches_args(
            rg_path,
            pattern=pattern,
            path=path,
            file_pattern=file_pattern,
            is_case_sensitive=action.case_sensitive,
        )
    elif output_mode == 'count':
        args = build_ripgrep_count_args(
            rg_path,
            pattern=pattern,
            path=path,
            file_pattern=file_pattern,
            is_case_sensitive=action.case_sensitive,
        )
    else:
        args = build_ripgrep_text_search_args(
            rg_path,
            pattern=pattern,
            path=path,
            file_pattern=file_pattern,
            context_lines=action.context_lines,
            is_case_sensitive=action.case_sensitive,
        )
    try:
        result = run_ripgrep_command(args)
    except Exception as exc:
        message = f'Error running ripgrep: {exc}'
        return _grep_failure(
            message=message,
            pattern=pattern,
            path=path,
            output_mode=output_mode,
        )
    if getattr(result, 'timed_out', False):
        message = 'Search timed out after 30s'
        return _grep_failure(
            message=message,
            pattern=pattern,
            path=path,
            output_mode=output_mode,
        )
    lines = [line for line in result.stdout.splitlines() if line]
    content = paginate_line_output(
        lines,
        offset=action.offset,
        head_limit=action.head_limit,
        empty_message=empty_message,
    )
    return make_grep_observation(
        pattern=pattern,
        path=path,
        output_mode=output_mode,
        lines=lines,
        content=content,
    )


def _run_python_mode(
    *,
    action: GrepAction,
    path: str,
    file_pattern: str,
    output_mode: str,
    regex: object,
    empty_message: str,
) -> GrepObservation | Observation:
    target_files = collect_python_target_files(path, file_pattern)
    if not target_files:
        return make_grep_observation(
            pattern=action.pattern,
            path=path,
            output_mode=output_mode,
            lines=[],
            content=empty_message,
        )

    if output_mode == 'files_with_matches':
        lines = collect_python_files_with_matches(target_files, regex=regex)  # type: ignore[arg-type]
    elif output_mode == 'count':
        lines = collect_python_match_counts(target_files, regex=regex)  # type: ignore[arg-type]
    else:
        lines = collect_python_match_results(
            target_files,
            regex=regex,  # type: ignore[arg-type]
            context_lines=action.context_lines,
        )

    content = paginate_line_output(
        lines,
        offset=action.offset,
        head_limit=action.head_limit,
        empty_message=empty_message,
    )
    return make_grep_observation(
        pattern=action.pattern,
        path=path,
        output_mode=output_mode,
        lines=lines,
        content=content,
    )
