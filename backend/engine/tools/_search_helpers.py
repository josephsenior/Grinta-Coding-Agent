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
from collections.abc import Callable
from typing import Any

from backend.engine.tools.ignore_filter import (
    get_ignore_spec,
    is_ignored_file,
    prune_ignored_dirs,
)
from backend.ledger.action import AgentThinkAction
from backend.utils.subprocess_bridge import run_bounded_subprocess_sync

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

SEARCH_RESULTS_TAG = '[SEARCH_RESULTS]'


def search_results_action(content: str, *, source_tool: str) -> AgentThinkAction:
    """Wrap ``content`` in the standard search payload envelope."""
    return AgentThinkAction(
        source_tool=source_tool,
        thought=f'{SEARCH_RESULTS_TAG}\n{content}',
    )


def search_error_action(message: str, *, source_tool: str) -> AgentThinkAction:
    """Return an error message in the same envelope so renderers treat it uniformly."""
    return search_results_action(message, source_tool=source_tool)


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
    source_tool: str,
    invalid_hint: str | None = None,
) -> tuple[re.Pattern[str] | None, AgentThinkAction | None]:
    if not pattern:
        return None, None
    flags = 0 if is_case_sensitive else re.IGNORECASE
    try:
        return re.compile(pattern, flags), None
    except re.error as exc:
        hint = (
            invalid_hint
            if invalid_hint is not None
            else f'Invalid regex in "pattern": {exc}.'
        )
        return None, search_error_action(hint, source_tool=source_tool)


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


def collect_python_target_files(path: str, file_pattern: str) -> list[str]:
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
            if not matches_search_file_pattern(
                file_path,
                file_name,
                file_pattern=file_pattern,
                spec_root=spec_root,
            ):
                continue
            target_files.append(file_path)

    return target_files


def format_python_file_listing(
    target_files: list[str], *, max_results: int
) -> str:
    output = '\n'.join(target_files[:max_results])
    return output or 'No matching files found.'


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


def build_ripgrep_file_discovery_args(
    rg_path: str,
    *,
    file_pattern: str,
    path: str,
) -> list[str]:
    args = [rg_path, '--files']
    for directory in SEARCH_EXCLUDED_DIRS:
        args.extend(['--glob', f'!**/{directory}/**'])
    if file_pattern:
        args.extend(['--glob', file_pattern])
    args.append(path)
    return args


def run_ripgrep_with_handler(
    args_builder: Callable[[], list[str]],
    *,
    max_lines: int,
    empty_message: str,
    source_tool: str,
) -> AgentThinkAction:
    try:
        result = run_ripgrep_command(args_builder())
    except Exception as exc:
        return search_error_action(f'Error running ripgrep: {exc}', source_tool=source_tool)
    return search_results_action(
        format_ripgrep_output(
            result.stdout,
            max_lines=max_lines,
            empty_message=empty_message,
        ),
        source_tool=source_tool,
    )


def build_ripgrep_text_search_args(
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


def collect_python_match_results(
    target_files: list[str],
    *,
    regex: re.Pattern[str],
    context_lines: int,
    max_results: int,
) -> str:
    results: list[str] = []
    match_count = 0
    for file_path in target_files:
        if match_count >= max_results:
            break

        file_matches = python_search_file_matches(
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


def has_ripgrep() -> str | None:
    """Return the path to ``rg`` if installed, else ``None``."""
    return shutil.which('rg')


def path_exists_or_error(path: str, *, source_tool: str) -> AgentThinkAction | None:
    if not os.path.exists(path):
        return search_error_action(
            f'Path does not exist: {path}', source_tool=source_tool
        )
    return None
