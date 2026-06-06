"""``grep`` tool — regex/text search across project files.

Searches for a regex pattern inside files under a directory, using ripgrep
when available and falling back to a pure-Python walker that respects the
workspace ignore spec.  Returns ripgrep-style ``path:line:content`` lines.

For file discovery (listing files matching a glob without scanning their
contents) use the ``glob`` tool instead.
"""

from __future__ import annotations

from backend.engine.tools._search_helpers import (
    collect_python_match_results,
    collect_python_target_files,
    compile_search_regex,
    format_ripgrep_output,
    has_ripgrep,
    run_ripgrep_with_handler,
    search_results_action,
    build_ripgrep_text_search_args,
)
from backend.engine.tools.common import create_tool_definition
from backend.ledger.action import AgentThinkAction

GREP_TOOL_NAME = 'grep'

_GREP_DESCRIPTION = """\
Search the project for a regex pattern inside file contents.

Use ``grep`` when you need to find lines of code, text, or symbols that
match a pattern.  Output is ripgrep-style ``path:line:content`` lines, with
optional context lines before and after each match.

For listing files that match a glob (without reading their contents), use
the ``glob`` tool instead.  For symbol-aware navigation (definitions,
references) use ``lsp``.
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
            'context_lines': {
                'type': 'integer',
                'description': (
                    'Lines of context to show before and after each match '
                    '(default: 2, max: 10).'
                ),
            },
            'case_sensitive': {
                'type': 'boolean',
                'description': 'Whether the search is case-sensitive (default: false).',
            },
            'max_results': {
                'type': 'integer',
                'description': (
                    'Maximum number of matching lines to return '
                    '(default: 50, max: 500).'
                ),
            },
        },
        required=['pattern'],
    )


def build_grep_action(
    pattern: str = '',
    path: str = '.',
    file_pattern: str = '',
    context_lines: int = 2,
    case_sensitive: bool | str = False,
    max_results: int = 50,
) -> AgentThinkAction:
    """Execute a regex text search.

    Tries ripgrep first since it is much faster and respects ``.gitignore``
    automatically.  Falls back to a pure-Python walker when ``rg`` is not
    on ``PATH``.
    """
    path = path or '.'
    context_lines = max(0, min(int(context_lines), 10))
    max_results = max(1, min(int(max_results), 500))
    is_case_sensitive = case_sensitive is True or str(case_sensitive).lower() == 'true'

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

    rg_path = has_ripgrep()
    if rg_path:
        return run_ripgrep_with_handler(
            lambda: build_ripgrep_text_search_args(
                rg_path,
                pattern=pattern,
                path=path,
                file_pattern=file_pattern,
                context_lines=context_lines,
                is_case_sensitive=is_case_sensitive,
                max_results=max_results,
            ),
            max_lines=max_results * (context_lines * 2 + 1) + 10,
            empty_message='No matches found.',
            source_tool=GREP_TOOL_NAME,
        )

    target_files = collect_python_target_files(path, file_pattern)
    if not target_files:
        return search_results_action(
            format_ripgrep_output(
                '',
                max_lines=1,
                empty_message='No matches found.',
            ),
            source_tool=GREP_TOOL_NAME,
        )

    return search_results_action(
        collect_python_match_results(
            target_files,
            regex=regex,
            context_lines=context_lines,
            max_results=max_results,
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
