"""``grep`` tool — regex/text search across project files.

Searches for a regex pattern inside files under a directory, using ripgrep
when available and falling back to a pure-Python walker that respects the
workspace ignore spec.

For file discovery (listing files matching a glob without scanning their
contents) use the ``glob`` tool instead.
"""

from __future__ import annotations

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
    format_ripgrep_output,
    has_ripgrep,
    paginate_line_output,
    resolve_search_pagination,
    run_ripgrep_command,
    search_error_action,
    search_results_action,
)
from backend.engine.tools.common import create_tool_definition
from backend.inference.tool_names import GREP_TOOL_NAME
from backend.ledger.action import AgentThinkAction

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


def create_grep_tool() -> dict:
    """Create the grep tool definition."""
    return create_tool_definition(  # type: ignore[no-any-return]
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
                    "Optional glob to limit which files are searched "
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
) -> AgentThinkAction:
    """Execute a regex text search."""
    path = path or '.'
    context_lines = max(0, min(int(context_lines), 10))
    is_case_sensitive = case_sensitive is True or str(case_sensitive).lower() == 'true'
    resolved_offset, resolved_head_limit = resolve_search_pagination(
        head_limit,
        offset,
    )
    mode = (output_mode or DEFAULT_GREP_OUTPUT_MODE).strip().lower()
    if mode not in GREP_OUTPUT_MODES:
        mode = DEFAULT_GREP_OUTPUT_MODE

    if not pattern:
        return _invalid_grep_arguments_action()

    regex, regex_error = compile_search_regex(
        pattern,
        is_case_sensitive=is_case_sensitive,
        source_tool=GREP_TOOL_NAME,
        invalid_hint=(
            f"Invalid regex in 'pattern' for grep: {{exc}}. "
            'Note: glob patterns (e.g. *.ts) belong to the `glob` tool, not `grep`.'
        ),
    )
    if regex_error is not None:
        return regex_error

    if not _path_exists(path):
        return search_results_action(
            f'Path does not exist: {path}', source_tool=GREP_TOOL_NAME
        )

    empty_message = 'No matches found.'
    rg_path = has_ripgrep()
    if rg_path:
        return _run_ripgrep_mode(
            rg_path,
            pattern=pattern,
            path=path,
            file_pattern=file_pattern,
            context_lines=context_lines,
            is_case_sensitive=is_case_sensitive,
            output_mode=mode,
            offset=resolved_offset,
            head_limit=resolved_head_limit,
            regex=regex,
            empty_message=empty_message,
        )

    return _run_python_mode(
        path=path,
        file_pattern=file_pattern,
        context_lines=context_lines,
        output_mode=mode,
        offset=resolved_offset,
        head_limit=resolved_head_limit,
        regex=regex,
        empty_message=empty_message,
    )


def _run_ripgrep_mode(
    rg_path: str,
    *,
    pattern: str,
    path: str,
    file_pattern: str,
    context_lines: int,
    is_case_sensitive: bool,
    output_mode: str,
    offset: int,
    head_limit: int | None,
    regex: object,
    empty_message: str,
) -> AgentThinkAction:
    if output_mode == 'files_with_matches':
        args = build_ripgrep_files_with_matches_args(
            rg_path,
            pattern=pattern,
            path=path,
            file_pattern=file_pattern,
            is_case_sensitive=is_case_sensitive,
        )
    elif output_mode == 'count':
        args = build_ripgrep_count_args(
            rg_path,
            pattern=pattern,
            path=path,
            file_pattern=file_pattern,
            is_case_sensitive=is_case_sensitive,
        )
    else:
        args = build_ripgrep_text_search_args(
            rg_path,
            pattern=pattern,
            path=path,
            file_pattern=file_pattern,
            context_lines=context_lines,
            is_case_sensitive=is_case_sensitive,
        )
    try:
        result = run_ripgrep_command(args)
    except Exception as exc:
        return search_error_action(
            f'Error running ripgrep: {exc}', source_tool=GREP_TOOL_NAME
        )
    if getattr(result, 'timed_out', False):
        return search_error_action(
            'Search timed out after 30s',
            source_tool=GREP_TOOL_NAME,
        )
    lines = result.stdout.splitlines()
    return search_results_action(
        paginate_line_output(
            lines,
            offset=offset,
            head_limit=head_limit,
            empty_message=empty_message,
        ),
        source_tool=GREP_TOOL_NAME,
    )


def _run_python_mode(
    *,
    path: str,
    file_pattern: str,
    context_lines: int,
    output_mode: str,
    offset: int,
    head_limit: int | None,
    regex: object,
    empty_message: str,
) -> AgentThinkAction:
    target_files = collect_python_target_files(path, file_pattern)
    if not target_files:
        return search_results_action(
            format_ripgrep_output('', max_lines=1, empty_message=empty_message),
            source_tool=GREP_TOOL_NAME,
        )

    if output_mode == 'files_with_matches':
        lines = collect_python_files_with_matches(target_files, regex=regex)  # type: ignore[arg-type]
    elif output_mode == 'count':
        lines = collect_python_match_counts(target_files, regex=regex)  # type: ignore[arg-type]
    else:
        lines = collect_python_match_results(
            target_files,
            regex=regex,  # type: ignore[arg-type]
            context_lines=context_lines,
        )

    return search_results_action(
        paginate_line_output(
            lines,
            offset=offset,
            head_limit=head_limit,
            empty_message=empty_message,
        ),
        source_tool=GREP_TOOL_NAME,
    )


def _invalid_grep_arguments_action() -> AgentThinkAction:
    return search_results_action(
        'grep requires a non-empty `pattern` argument. Use the `glob` tool to list files.',
        source_tool=GREP_TOOL_NAME,
    )


def _path_exists(path: str) -> bool:
    import os

    return os.path.exists(path)
