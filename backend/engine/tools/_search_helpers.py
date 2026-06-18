"""Shared helpers for the ``grep`` and ``glob`` discovery tools.

Both tools walk the project tree to gather candidate paths while respecting the
workspace ignore spec, and both prefer a ripgrep fast path when one is
available on ``PATH``.  Keeping these primitives in a single module ensures
that the two tools stay consistent in their traversal, exclusions, and
output formatting, and prevents drift between ripgrep/Python fallbacks.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from typing import Any

from backend.engine.tools.ignore_filter import (
    get_ignore_spec,
    is_ignored_file,
    prune_ignored_dirs,
)
from backend.ledger.observation.search import GlobObservation, GrepObservation
from backend.utils.async_helpers.subprocess_bridge import run_bounded_subprocess_sync

# Directories excluded from the file walker / ripgrep discovery.  Shared by
# the ``grep`` and ``glob`` tools so they share the same noise floor.
SEARCH_EXCLUDED_DIRS: tuple[str, ...] = (
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

# Smaller exclusion set for ripgrep text search — it already honours
# ``.gitignore`` and skipping these large trees speeds things up considerably.
SEARCH_RG_EXCLUDED_DIRS: tuple[str, ...] = (
    '.venv',
    'node_modules',
    '__pycache__',
    '.git',
)

DEFAULT_SEARCH_HEAD_LIMIT = 200
MAX_SEARCH_HEAD_LIMIT = 1000
GREP_OUTPUT_MODES = frozenset({'content', 'files_with_matches', 'count'})
DEFAULT_GREP_OUTPUT_MODE = 'files_with_matches'


def should_prefix_hidden_file_pattern(file_pattern: str) -> bool:
    return (
        bool(file_pattern)
        and file_pattern.startswith('.')
        and not file_pattern.startswith(('*', '?', '!'))
    )


def wrap_literal_file_pattern(file_pattern: str) -> str:
    if file_pattern and not any(char in file_pattern for char in '*?[]'):
        return f'*{file_pattern}*'
    return file_pattern


def normalize_glob_pattern(pattern: str) -> str:
    """Prepend a leading ``*`` to hidden-file globs so they match anywhere."""
    if should_prefix_hidden_file_pattern(pattern):
        return f'*{pattern}'
    return pattern


def compile_search_regex(
    pattern: str,
    *,
    is_case_sensitive: bool,
    source_tool: str = '',
    invalid_hint: str | None = None,
) -> tuple[re.Pattern[str] | None, str | None]:
    if not pattern:
        return None, None
    flags = 0 if is_case_sensitive else re.IGNORECASE
    try:
        return re.compile(pattern, flags), None
    except re.error as exc:
        if invalid_hint is not None:
            hint = invalid_hint.replace('{exc}', str(exc))
        else:
            hint = f'Invalid regex in "pattern": {exc}.'
        return None, hint


def _count_grep_stats(lines: list[str], output_mode: str) -> tuple[int, int]:
    """Return ``(match_count, file_count)`` from raw result lines."""
    if not lines:
        return 0, 0
    if output_mode == 'files_with_matches':
        count = len(lines)
        return count, count
    if output_mode == 'count':
        total = 0
        for line in lines:
            if ':' in line:
                try:
                    total += int(line.rsplit(':', 1)[-1])
                except ValueError:
                    total += 1
            else:
                total += 1
        return total, len(lines)
    grouped: dict[str, int] = {}
    for line in lines:
        if ':' in line:
            filepath = line.split(':', 1)[0]
            grouped[filepath] = grouped.get(filepath, 0) + 1
    if grouped:
        return sum(grouped.values()), len(grouped)
    return len(lines), 1


def make_grep_observation(
    *,
    pattern: str,
    path: str,
    output_mode: str,
    lines: list[str],
    content: str,
    error: str = '',
) -> GrepObservation:
    """Build a structured grep observation from execution output."""
    match_count, file_count = _count_grep_stats(lines, output_mode)
    obs = GrepObservation(
        content=content,
        pattern=pattern,
        path=path,
        output_mode=output_mode,
        lines=lines,
        match_count=match_count,
        file_count=file_count,
        error=error,
    )
    if error:
        attach_search_error_tool_result(
            obs,
            tool='grep',
            pattern=pattern,
            path=path,
            output_mode=output_mode,
        )
    return obs


def make_glob_observation(
    *,
    pattern: str,
    path: str,
    files: list[str],
    content: str,
    error: str = '',
) -> GlobObservation:
    """Build a structured glob observation from execution output."""
    file_count = len(files)
    obs = GlobObservation(
        content=content,
        pattern=pattern,
        path=path,
        files=files,
        file_count=file_count,
        error=error,
    )
    if error:
        attach_search_error_tool_result(
            obs,
            tool='glob',
            pattern=pattern,
            path=path,
        )
    return obs


def attach_search_error_tool_result(
    observation: GrepObservation | GlobObservation,
    *,
    tool: str,
    pattern: str,
    path: str,
    output_mode: str | None = None,
) -> None:
    from backend.execution.aes.structured_edit_errors import (
        build_search_error_tool_result,
    )

    message = str(getattr(observation, 'error', '') or observation.content or '')
    observation.tool_result = build_search_error_tool_result(
        tool=tool,
        message=message,
        pattern=pattern,
        path=path,
        output_mode=output_mode,
    )


def matches_search_file_pattern(
    file_path: str,
    file_name: str,
    *,
    file_pattern: str,
    spec_root: str,
) -> bool:
    import fnmatch

    if not file_pattern:
        return True
    rel_path = os.path.relpath(file_path, spec_root).replace(os.path.sep, '/')
    return fnmatch.fnmatch(file_name, file_pattern) or fnmatch.fnmatch(
        rel_path,
        file_pattern,
    )


def collect_python_target_files(
    path: str,
    file_pattern: str,
    *,
    walk_timeout_seconds: float = 30.0,
) -> list[str]:
    spec_root = path if os.path.isdir(path) else os.path.dirname(path) or '.'
    spec = get_ignore_spec(spec_root)
    target_files: list[str] = []
    deadline = time.monotonic() + max(1.0, walk_timeout_seconds)

    if os.path.isfile(path):
        current_root = os.path.dirname(path) or '.'
        if not is_ignored_file(spec_root, current_root, os.path.basename(path), spec):
            target_files.append(path)
        return target_files

    for root, dirs, files in os.walk(path):
        if time.monotonic() >= deadline:
            break
        prune_ignored_dirs(spec_root, root, dirs, spec)
        for file_name in files:
            if time.monotonic() >= deadline:
                break
            if is_ignored_file(spec_root, root, file_name, spec):
                continue
            file_path = os.path.join(root, file_name)
            if not matches_search_file_pattern(
                file_path,
                file_name,
                file_pattern=file_pattern,
                spec_root=spec_root,
            ):
                continue
            target_files.append(file_path)

    return target_files


def resolve_search_pagination(
    raw_head_limit: object = None,
    raw_offset: object = None,
    *,
    default_head_limit: int = DEFAULT_SEARCH_HEAD_LIMIT,
    max_head_limit: int = MAX_SEARCH_HEAD_LIMIT,
) -> tuple[int, int | None]:
    """Return ``(offset, head_limit)``; ``head_limit=None`` means unlimited."""
    try:
        if raw_head_limit is None:
            head_limit = default_head_limit
        elif isinstance(raw_head_limit, (int, str)):
            head_limit = int(raw_head_limit)
        else:
            head_limit = default_head_limit
    except (TypeError, ValueError):
        head_limit = default_head_limit
    try:
        if isinstance(raw_offset, (int, str)):
            offset = max(0, int(raw_offset))
        else:
            offset = 0
    except (TypeError, ValueError):
        offset = 0
    if head_limit == 0:
        return offset, None
    return offset, max(1, min(head_limit, max_head_limit))


def paginate_line_output(
    lines: list[str],
    *,
    offset: int,
    head_limit: int | None,
    empty_message: str,
) -> str:
    if head_limit is None:
        sliced = lines[offset:]
    else:
        sliced = lines[offset : offset + head_limit]
    output = '\n'.join(line for line in sliced if line)
    if not output:
        return empty_message
    if head_limit is not None and len(lines) > offset + head_limit:
        remaining = len(lines) - offset - head_limit
        output += f'\n... ({remaining} more; increase head_limit or use offset)'
    return output


def format_python_file_listing(
    target_files: list[str],
    *,
    offset: int = 0,
    head_limit: int | None = DEFAULT_SEARCH_HEAD_LIMIT,
) -> str:
    return paginate_line_output(
        target_files,
        offset=offset,
        head_limit=head_limit,
        empty_message='No matching files found.',
    )


def run_ripgrep_command(args: list[str]) -> Any:
    return run_bounded_subprocess_sync(
        args,
        process_timeout=30.0,
        max_bytes_per_stream=2 * 1024 * 1024,
    )


def format_ripgrep_output(stdout: str, *, max_lines: int, empty_message: str) -> str:
    lines = stdout.splitlines()[:max_lines]
    output = '\n'.join(lines)
    return output or empty_message


def _append_ripgrep_glob_filters(args: list[str], file_pattern: str) -> None:
    for directory in SEARCH_EXCLUDED_DIRS:
        args.extend(['--glob', f'!**/{directory}/**'])
    if file_pattern:
        args.extend(['--glob', file_pattern])


def build_ripgrep_file_discovery_args(
    rg_path: str,
    *,
    file_pattern: str,
    path: str,
) -> list[str]:
    args = [rg_path, '--files']
    _append_ripgrep_glob_filters(args, file_pattern)
    args.append(path)
    return args


def build_ripgrep_files_with_matches_args(
    rg_path: str,
    *,
    pattern: str,
    path: str,
    file_pattern: str,
    is_case_sensitive: bool,
) -> list[str]:
    args = [rg_path, '-l']
    if not is_case_sensitive:
        args.append('--ignore-case')
    _append_ripgrep_glob_filters(args, file_pattern)
    args.extend([pattern, path])
    return args


def build_ripgrep_count_args(
    rg_path: str,
    *,
    pattern: str,
    path: str,
    file_pattern: str,
    is_case_sensitive: bool,
) -> list[str]:
    args = [rg_path, '-c', '--no-heading']
    if not is_case_sensitive:
        args.append('--ignore-case')
    _append_ripgrep_glob_filters(args, file_pattern)
    args.extend([pattern, path])
    return args


def build_ripgrep_text_search_args(
    rg_path: str,
    *,
    pattern: str,
    path: str,
    file_pattern: str,
    context_lines: int,
    is_case_sensitive: bool,
) -> list[str]:
    args = [
        rg_path,
        f'--context={context_lines}',
        '--line-number',
        '--no-heading',
    ]
    if not is_case_sensitive:
        args.append('--ignore-case')
    for directory in SEARCH_RG_EXCLUDED_DIRS:
        args.extend(['--glob', f'!**/{directory}/**'])
    if file_pattern:
        args.extend(['--glob', file_pattern])
    args.extend([pattern, path])
    return args


def format_python_match_block(
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
        prefix = (
            f'{line_index + 1}:' if line_index == match_index else f'{line_index + 1}-'
        )
        block.append(f'{fpath}:{prefix}{lines[line_index].rstrip()}')
    return '\n'.join(block)


def python_search_file_matches(
    fpath: str,
    *,
    regex: re.Pattern[str],
    context_lines: int,
    remaining_results: int,
) -> list[str]:
    try:
        with open(fpath, 'r', encoding='utf-8', errors='ignore') as file_handle:
            lines = file_handle.readlines()
    except OSError:
        return []

    file_matches: list[str] = []
    for index, line in enumerate(lines):
        if not regex.search(line):
            continue
        file_matches.append(
            format_python_match_block(
                fpath,
                lines,
                match_index=index,
                context_lines=context_lines,
            )
        )
        if len(file_matches) >= remaining_results:
            break
    return file_matches


def _python_file_has_match(fpath: str, *, regex: re.Pattern[str]) -> bool:
    try:
        with open(fpath, 'r', encoding='utf-8', errors='ignore') as file_handle:
            for line in file_handle:
                if regex.search(line):
                    return True
    except OSError:
        return False
    return False


def _python_file_match_count(fpath: str, *, regex: re.Pattern[str]) -> int:
    count = 0
    try:
        with open(fpath, 'r', encoding='utf-8', errors='ignore') as file_handle:
            for line in file_handle:
                if regex.search(line):
                    count += 1
    except OSError:
        return 0
    return count


def collect_python_files_with_matches(
    target_files: list[str],
    *,
    regex: re.Pattern[str],
) -> list[str]:
    return [
        file_path
        for file_path in target_files
        if _python_file_has_match(file_path, regex=regex)
    ]


def collect_python_match_counts(
    target_files: list[str],
    *,
    regex: re.Pattern[str],
) -> list[str]:
    lines: list[str] = []
    for file_path in target_files:
        count = _python_file_match_count(file_path, regex=regex)
        if count:
            lines.append(f'{file_path}:{count}')
    return lines


def collect_python_match_results(
    target_files: list[str],
    *,
    regex: re.Pattern[str],
    context_lines: int,
) -> list[str]:
    results: list[str] = []
    for file_path in target_files:
        file_matches = python_search_file_matches(
            file_path,
            regex=regex,
            context_lines=context_lines,
            remaining_results=10_000,
        )
        if file_matches:
            results.extend(file_matches)
            results.append('--')
    if results and results[-1] == '--':
        results.pop()
    return results


def has_ripgrep() -> str | None:
    """Return the path to ``rg`` if installed, else ``None``."""
    return shutil.which('rg')


def path_exists_error(path: str) -> str | None:
    if not os.path.exists(path):
        return f'Path does not exist: {path}'
    return None
