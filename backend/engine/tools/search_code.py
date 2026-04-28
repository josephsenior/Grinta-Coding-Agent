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


def _normalize_search_inputs(pattern: str, file_pattern: str) -> tuple[str, str]:
    import re

    normalized_pattern = pattern
    normalized_file_pattern = file_pattern

    if (
        normalized_file_pattern
        and not normalized_file_pattern.startswith(('*', '?', '!'))
        and normalized_file_pattern.startswith('.')
    ):
        normalized_file_pattern = f'*{normalized_file_pattern}'

    if (
        not normalized_pattern
        and normalized_file_pattern
        and not any(c in normalized_file_pattern for c in '*?[]')
    ):
        normalized_file_pattern = f'*{normalized_file_pattern}*'

    if (
        normalized_pattern
        and not normalized_file_pattern
        and re.match(r'^[\w\*\.\-\?]+$', normalized_pattern)
        and (
            normalized_pattern.startswith(('*', '?', '.'))
            or any(x in normalized_pattern for x in ['test', 'tests', 'util', 'src'])
        )
    ):
        normalized_file_pattern = normalized_pattern
        if not any(c in normalized_file_pattern for c in '*?[]'):
            normalized_file_pattern = f'*{normalized_file_pattern}*'
        normalized_pattern = ''

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
    import subprocess

    if not pattern:
        # File discovery mode
        args = [rg_path, '--files']
        for d in _SEARCH_EXCLUDED_DIRS:
            args.extend(['--glob', f'!**/{d}/**'])
        if file_pattern:
            args.extend(['--glob', file_pattern])
        args.append(path)

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                check=False,
            )
            lines = result.stdout.splitlines()[:max_results]
            out = '\n'.join(lines)
            if not out:
                out = 'No matching files found.'
            return AgentThinkAction(
                source_tool='search_code',
                thought=f'<search_results>\n{out}\n</search_results>',
            )
        except Exception as e:
            return AgentThinkAction(
                source_tool='search_code',
                thought=f'<search_results>\nError running ripgrep: {e}\n</search_results>',
            )

    # Search mode
    args = [
        rg_path,
        f'--context={context_lines}',
        f'--max-count={max_results}',
        '--line-number',
        '--no-heading',
    ]
    if not is_case_sensitive:
        args.append('--ignore-case')
    # Let ripgrep handle .gitignore naturally, but enforce a few fail-safes
    # if the user forgot them in .gitignore
    for d in ['.venv', 'node_modules', '__pycache__', '.git']:
        args.extend(['--glob', f'!**/{d}/**'])
    if file_pattern:
        args.extend(['--glob', file_pattern])

    args.append(pattern)
    args.append(path)

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=False,
        )
        out = result.stdout
        limit = max_results * (context_lines * 2 + 1) + 10
        lines = out.splitlines()[:limit]
        out_limited = '\n'.join(lines)
        if not out_limited:
            out_limited = 'No matches found.'
        return AgentThinkAction(
            source_tool='search_code',
            thought=f'<search_results>\n{out_limited}\n</search_results>',
        )
    except Exception as e:
        return AgentThinkAction(thought=f'<search_results>\\nError running ripgrep: {e}\
</search_results>')


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
    import re

    if not os.path.exists(path):
        return AgentThinkAction(
            source_tool='search_code',
            thought=f'<search_results>\nPath does not exist: {path}\n</search_results>',
        )

    regex = None
    if pattern:
        flags = 0 if is_case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern, flags)
        except re.error as exc:
            return _invalid_search_regex_action(f'Invalid regex pattern: {exc}')

    target_files = _collect_python_search_target_files(path, file_pattern)

    if not pattern:
        lines = target_files[:max_results]
        out = '\n'.join(lines)
        if not out:
            out = 'No matching files found.'
        return _search_results_action(out)

    results: list[str] = []
    match_count = 0
    for fpath in target_files:
        if match_count >= max_results:
            break

        file_matches = _python_search_file_matches(
            fpath,
            regex=regex,
            context_lines=context_lines,
            remaining_results=max_results - match_count,
        )
        match_count += len(file_matches)

        if file_matches:
            results.extend(file_matches)
            results.append('--')

    out = '\n'.join(results)
    if not out:
        out = 'No matches found.'
    return _search_results_action(out)
