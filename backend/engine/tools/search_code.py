"""Fast code search tool for the Orchestrator agent.

Eliminates the grep→parse→regrep cycle by providing a single
structured search interface that tries ripgrep first, then falls
back to pure Python traversal.
"""

from __future__ import annotations

from backend.engine.tools.common import create_tool_definition
from backend.engine.tools.ignore_filter import (
    get_ignore_spec,
    is_ignored_file,
    prune_ignored_dirs,
)
from backend.ledger.action import AgentThinkAction

_SEARCH_EXCLUDED_DIRS = (
    '.git',
    '.venv',
    'venv',
    '.mypy_cache',
    '.pytest_cache',
    '.ruff_cache',
    '__pycache__',
    'node_modules',
    '.tmp_cli_manual',
    'logs',
    'storage',
    'build',
    'dist',
)

_SEARCH_CODE_DESCRIPTION = """\
Search for text patterns, symbols, or file paths in the codebase using ripgrep (falls back to Python traversal).

Modes:
1. Text/regex search — set `pattern` to a regex pattern to find matching lines inside files.
2. File discovery — omit `pattern` entirely, and set `file_pattern` to a glob pattern to list matching files.

Use this when target location is unknown. For dependency traversal, use `explore_tree_structure`.
"""

SEARCH_CODE_TOOL_NAME = 'search_code'


def _should_prefix_hidden_file_pattern(file_pattern: str) -> bool:
    return bool(file_pattern) and file_pattern.startswith('.') and not file_pattern.startswith(
        ('*', '?', '!')
    )


def _wrap_literal_file_pattern(file_pattern: str) -> str:
    if file_pattern and not any(char in file_pattern for char in '*?[]'):
        return f'*{file_pattern}*'
    return file_pattern


def _looks_like_file_pattern_hint(pattern: str) -> bool:
    import re

    if not re.match(r'^[\w\*\.\-\?]+$', pattern):
        return False
    if pattern.startswith(('*', '?', '.')):
        return True
    return any(token in pattern for token in ['test', 'tests', 'util', 'src'])


def _normalize_search_inputs(pattern: str, file_pattern: str) -> tuple[str, str]:
    normalized_pattern = pattern
    normalized_file_pattern = file_pattern

    if _should_prefix_hidden_file_pattern(normalized_file_pattern):
        normalized_file_pattern = f'*{normalized_file_pattern}'

    if not normalized_pattern and normalized_file_pattern:
        return normalized_pattern, _wrap_literal_file_pattern(normalized_file_pattern)

    if normalized_pattern and not normalized_file_pattern and _looks_like_file_pattern_hint(
        normalized_pattern
    ):
        return '', _wrap_literal_file_pattern(normalized_pattern)

    return normalized_pattern, normalized_file_pattern


def _invalid_search_regex_action(message: str) -> AgentThinkAction:
    return AgentThinkAction(
        source_tool='search_code',
        thought=f'<search_results>\n{message}\n</search_results>',
    )


def _validate_search_regex(
    pattern: str,
    *,
    is_case_sensitive: bool,
) -> AgentThinkAction | None:
    import re

    if not pattern:
        return None

    flags = 0 if is_case_sensitive else re.IGNORECASE
    try:
        re.compile(pattern, flags)
    except re.error as exc:
        return _invalid_search_regex_action(
            f"Invalid regex in 'pattern': {exc}. Did you mean to use 'file_pattern' for glob patterns like '*.ts'?"
        )
    return None


def _matches_search_file_pattern(
    file_path: str,
    file_name: str,
    *,
    file_pattern: str,
    spec_root: str,
) -> bool:
    import fnmatch
    import os

    if not file_pattern:
        return True
    rel_path = os.path.relpath(file_path, spec_root).replace(os.path.sep, '/')
    return fnmatch.fnmatch(file_name, file_pattern) or fnmatch.fnmatch(
        rel_path,
        file_pattern,
    )


def _collect_python_search_target_files(path: str, file_pattern: str) -> list[str]:
    import os

    spec_root = path if os.path.isdir(path) else os.path.dirname(path) or '.'
    spec = get_ignore_spec(spec_root)
    target_files: list[str] = []

    if os.path.isfile(path):
        current_root = os.path.dirname(path) or '.'
        if not is_ignored_file(spec_root, current_root, os.path.basename(path), spec):
            target_files.append(path)
        return target_files

    for root, dirs, files in os.walk(path):
        prune_ignored_dirs(spec_root, root, dirs, spec)
        for file_name in files:
            if is_ignored_file(spec_root, root, file_name, spec):
                continue
            file_path = os.path.join(root, file_name)
            if not _matches_search_file_pattern(
                file_path,
                file_name,
                file_pattern=file_pattern,
                spec_root=spec_root,
            ):
                continue
            target_files.append(file_path)

    return target_files


def _format_python_search_match_block(
    fpath: str,
    lines: list[str],
    *,
    match_index: int,
    context_lines: int,
) -> str:
    start = max(0, match_index - context_lines)
    end = min(len(lines), match_index + context_lines + 1)
    block: list[str] = []
    for line_index in range(start, end):
        prefix = f'{line_index + 1}:' if line_index == match_index else f'{line_index + 1}-'
        block.append(f'{fpath}:{prefix}{lines[line_index].rstrip()}')
    return '\n'.join(block)


def _python_search_file_matches(
    fpath: str,
    *,
    regex: object,
    context_lines: int,
    remaining_results: int,
) -> list[str]:
    try:
        with open(fpath, 'r', encoding='utf-8', errors='ignore') as file_handle:  # type: ignore
            lines = file_handle.readlines()  # type: ignore
    except OSError:
        return []

    file_matches: list[str] = []
    for index, line in enumerate(lines):
        if not regex.search(line):  # type: ignore[attr-defined]
            continue
        file_matches.append(
            _format_python_search_match_block(
                fpath,
                lines,
                match_index=index,
                context_lines=context_lines,
            )
        )
        if len(file_matches) >= remaining_results:
            break
    return file_matches


def _search_results_action(content: str) -> AgentThinkAction:
    return AgentThinkAction(thought=f'<search_results>\n{content}\n</search_results>')


def create_search_code_tool() -> dict:
    """Create the search_code tool definition."""
    return create_tool_definition(  # type: ignore
        name=SEARCH_CODE_TOOL_NAME,
        description=_SEARCH_CODE_DESCRIPTION,
        properties={
            'pattern': {
                'type': 'string',
                'description': (
                    "Regex pattern for text search (e.g., 'function\\s+\\w+'). "
                    "Leave empty to list files only."
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
                    "Glob pattern for file filtering (e.g., '*.ts', 'src/**/*.test.js'). "
                    "Leave empty to search all text files."
                ),
            },
            'context_lines': {
                'type': 'integer',
                'description': 'Lines of context to show before and after each match (default: 2).',
            },
            'case_sensitive': {
                'type': 'boolean',
                'description': 'Whether the search is case-sensitive (default: false).',
            },
            'max_results': {
                'type': 'integer',
                'description': 'Maximum number of matching lines to return (default: 50).',
            },
        },
        required=[],  # all params optional; tool is flexible
    )


def build_search_code_action(
    pattern: str = '',
    path: str = '.',
    file_pattern: str = '',
    context_lines: int = 2,
    case_sensitive: bool | str = False,
    max_results: int = 50,
) -> AgentThinkAction:
    """Perform the code search directly in pure Python (with ripgrep fast-path).

    Tries ripgrep (rg) via subprocess first since it is much faster and respects
    .gitignore automatically. Falls back to pure Python traversal.
    """
    import shutil

    path = path or '.'
    context_lines = max(0, min(int(context_lines), 10))
    max_results = max(1, min(int(max_results), 500))
    is_case_sensitive = case_sensitive is True or str(case_sensitive).lower() == 'true'
    pattern, file_pattern = _normalize_search_inputs(pattern, file_pattern)

    regex_error = _validate_search_regex(
        pattern,
        is_case_sensitive=is_case_sensitive,
    )
    if regex_error is not None:
        return regex_error

    # 1. Fast path: Ripgrep
    rg_path = shutil.which('rg')
    if rg_path:
        return _search_with_ripgrep(
            rg_path,
            pattern,
            path,
            file_pattern,
            context_lines,
            is_case_sensitive,
            max_results,
        )

    # 2. Fallback: Pure Python
    return _search_with_python(
        pattern, path, file_pattern, context_lines, is_case_sensitive, max_results
    )


def _run_ripgrep_command(args: list[str]):
    import subprocess

    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
    )


def _format_ripgrep_output(stdout: str, *, max_lines: int, empty_message: str) -> str:
    lines = stdout.splitlines()[:max_lines]
    output = '\n'.join(lines)
    return output or empty_message


def _ripgrep_error_action(exc: Exception) -> AgentThinkAction:
    return _search_results_action(f'Error running ripgrep: {exc}')


def _build_ripgrep_file_discovery_args(
    rg_path: str,
    *,
    file_pattern: str,
    path: str,
) -> list[str]:
    args = [rg_path, '--files']
    for directory in _SEARCH_EXCLUDED_DIRS:
        args.extend(['--glob', f'!**/{directory}/**'])
    if file_pattern:
        args.extend(['--glob', file_pattern])
    args.append(path)
    return args


def _search_ripgrep_file_discovery(
    rg_path: str,
    *,
    file_pattern: str,
    path: str,
    max_results: int,
) -> AgentThinkAction:
    try:
        result = _run_ripgrep_command(
            _build_ripgrep_file_discovery_args(
                rg_path,
                file_pattern=file_pattern,
                path=path,
            )
        )
    except Exception as exc:
        return _ripgrep_error_action(exc)
    return _search_results_action(
        _format_ripgrep_output(
            result.stdout,
            max_lines=max_results,
            empty_message='No matching files found.',
        )
    )


def _build_ripgrep_search_args(
    rg_path: str,
    *,
    pattern: str,
    path: str,
    file_pattern: str,
    context_lines: int,
    is_case_sensitive: bool,
    max_results: int,
) -> list[str]:
    args = [
        rg_path,
        f'--context={context_lines}',
        f'--max-count={max_results}',
        '--line-number',
        '--no-heading',
    ]
    if not is_case_sensitive:
        args.append('--ignore-case')
    for directory in ['.venv', 'node_modules', '__pycache__', '.git']:
        args.extend(['--glob', f'!**/{directory}/**'])
    if file_pattern:
        args.extend(['--glob', file_pattern])
    args.extend([pattern, path])
    return args


def _search_ripgrep_matches(
    rg_path: str,
    *,
    pattern: str,
    path: str,
    file_pattern: str,
    context_lines: int,
    is_case_sensitive: bool,
    max_results: int,
) -> AgentThinkAction:
    try:
        result = _run_ripgrep_command(
            _build_ripgrep_search_args(
                rg_path,
                pattern=pattern,
                path=path,
                file_pattern=file_pattern,
                context_lines=context_lines,
                is_case_sensitive=is_case_sensitive,
                max_results=max_results,
            )
        )
    except Exception as exc:
        return _ripgrep_error_action(exc)

    return _search_results_action(
        _format_ripgrep_output(
            result.stdout,
            max_lines=max_results * (context_lines * 2 + 1) + 10,
            empty_message='No matches found.',
        )
    )


def _search_with_ripgrep(
    rg_path: str,
    pattern: str,
    path: str,
    file_pattern: str,
    context_lines: int,
    is_case_sensitive: bool,
    max_results: int,
) -> AgentThinkAction:
    """Execute ripgrep directly via subprocess."""
    if not pattern:
        return _search_ripgrep_file_discovery(
            rg_path,
            file_pattern=file_pattern,
            path=path,
            max_results=max_results,
        )

    return _search_ripgrep_matches(
        rg_path,
        pattern=pattern,
        path=path,
        file_pattern=file_pattern,
        context_lines=context_lines,
        is_case_sensitive=is_case_sensitive,
        max_results=max_results,
    )


def _compile_python_search_regex(
    pattern: str,
    *,
    is_case_sensitive: bool,
) -> tuple[object | None, AgentThinkAction | None]:
    import re

    if not pattern:
        return None, None

    flags = 0 if is_case_sensitive else re.IGNORECASE
    try:
        return re.compile(pattern, flags), None
    except re.error as exc:
        return None, _invalid_search_regex_action(f'Invalid regex pattern: {exc}')


def _format_python_file_listing(target_files: list[str], *, max_results: int) -> str:
    output = '\n'.join(target_files[:max_results])
    return output or 'No matching files found.'


def _collect_python_search_results(
    target_files: list[str],
    *,
    regex: object,
    context_lines: int,
    max_results: int,
) -> str:
    results: list[str] = []
    match_count = 0
    for file_path in target_files:
        if match_count >= max_results:
            break

        file_matches = _python_search_file_matches(
            file_path,
            regex=regex,
            context_lines=context_lines,
            remaining_results=max_results - match_count,
        )
        match_count += len(file_matches)

        if file_matches:
            results.extend(file_matches)
            results.append('--')

    return '\n'.join(results) or 'No matches found.'


def _search_with_python(
    pattern: str,
    path: str,
    file_pattern: str,
    context_lines: int,
    is_case_sensitive: bool,
    max_results: int,
) -> AgentThinkAction:
    """Execute search using pure Python standard library."""
    import os

    if not os.path.exists(path):
        return AgentThinkAction(
            source_tool='search_code',
            thought=f'<search_results>\nPath does not exist: {path}\n</search_results>',
        )

    regex, regex_error = _compile_python_search_regex(
        pattern,
        is_case_sensitive=is_case_sensitive,
    )
    if regex_error is not None:
        return regex_error

    target_files = _collect_python_search_target_files(path, file_pattern)

    if not pattern:
        return _search_results_action(
            _format_python_file_listing(target_files, max_results=max_results)
        )

    return _search_results_action(
        _collect_python_search_results(
            target_files,
            regex=regex,
            context_lines=context_lines,
            max_results=max_results,
        )
    )
