"""Smart output parsing for shell command results.

Detects output type and parses it into structured, visually appealing display.
Supports: pytest, git, npm/yarn/pip, ls, find, curl, and generic text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from rich.markup import escape as _markup_escape

from backend.cli.theme import (
    CLR_SECONDARY,
    CLR_STATUS_ERR,
    CLR_STATUS_OK,
    CLR_STATUS_WARN,
)


@dataclass
class ParsedTestResult:
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    lines: list[tuple[str, str, str]] = field(default_factory=list)
    duration: str = ''
    summary: str = ''
    has_failures: bool = False


@dataclass
class ParsedGitStatus:
    staged: list[str] = field(default_factory=list)
    unstaged: list[str] = field(default_factory=list)
    untracked: list[str] = field(default_factory=list)
    ahead: int = 0
    behind: int = 0
    clean: bool = False


@dataclass
class ParsedLsOutput:
    files: list[tuple[str, str, str]] = field(default_factory=list)
    """(icon, name, detail) tuples"""
    dirs: list[tuple[str, str]] = field(default_factory=list)
    total: int = 0


@dataclass
class ParsedGitDiff:
    files: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ShellOutput:
    kind: str = 'plain'
    lines: list[str] = field(default_factory=list)
    parsed_test: ParsedTestResult | None = None
    parsed_git_status: ParsedGitStatus | None = None
    parsed_ls: ParsedLsOutput | None = None
    truncated: bool = False
    first_line: str = ''
    exit_code: int | None = None


_OUTPUT_TYPE_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ('pytest', ('pytest', 'python -m pytest')),
    ('coverage', ('coverage',)),
    ('git_status', ('git status',)),
    ('git_diff', ('git diff',)),
    ('git_log', ('git log',)),
    ('git_branch', ('git branch',)),
    ('npm_install', ('npm install', 'npm i')),
    ('yarn_install', ('yarn install',)),
    ('pip_install', ('pip install', 'pip3 install')),
    ('curl', ('curl ',)),
    ('ls', ('ls ', 'ls')),
    ('find', ('find ',)),
    ('ping', ('ping ',)),
    ('linter', ('ruff', 'flake8', 'mypy')),
]

_PYTEST_SUMMARY_PATTERNS: list[tuple[str, str]] = [
    (r'(\d+) passed', 'passed'),
    (r'(\d+) failed', 'failed'),
    (r'(\d+) error', 'errors'),
    (r'(\d+) skipped', 'skipped'),
]

_PYTEST_SUMMARY_KEYWORDS: tuple[str, ...] = (
    ' passed',
    ' failed',
    ' error',
    ' skipped',
)

_PYTEST_SUMMARY_FORMATS: list[tuple[str, str, str]] = [
    ('passed', CLR_STATUS_OK, 'passed'),
    ('failed', CLR_STATUS_ERR, 'failed'),
    ('skipped', CLR_SECONDARY, 'skipped'),
]


def _match_command_pattern(cmd_lower: str, patterns: tuple[str, ...]) -> bool:
    for pattern in patterns:
        if pattern in cmd_lower or cmd_lower.startswith(pattern):
            return True
    return False


def detect_output_type(command: str, output: str) -> str:
    """Guess the output type from command + output patterns."""
    cmd_lower = command.lower()
    out_lower = output.lower()

    for output_type, patterns in _OUTPUT_TYPE_PATTERNS:
        if _match_command_pattern(cmd_lower, patterns):
            return output_type

    if out_lower.startswith('usage:'):
        return 'help'
    return 'plain'


def _is_pytest_summary_line(stripped: str) -> bool:
    for kw in _PYTEST_SUMMARY_KEYWORDS:
        if kw in stripped:
            return True
    return False


def _apply_pytest_summary_counts(result: ParsedTestResult, stripped: str) -> None:
    for pattern, attr in _PYTEST_SUMMARY_PATTERNS:
        m = re.search(pattern, stripped)
        if m:
            setattr(result, attr, int(m.group(1)))
    if result.failed:
        result.has_failures = True
    m = re.search(r'[\d.]+s', stripped)
    if m:
        result.duration = m.group()
    result.summary = stripped


def _determine_test_status(stripped: str) -> str:
    if 'FAILED' in stripped:
        return 'fail'
    if 'SKIPPED' in stripped:
        return 'skip'
    return 'pass'


def _parse_pytest_test_line(
    result: ParsedTestResult, stripped: str
) -> None:
    if '::test_' not in stripped and '---' not in stripped:
        return
    status = _determine_test_status(stripped)
    parts = stripped.split('::')
    if len(parts) >= 2:
        file_part = parts[0].strip()
        test_part = '::'.join(parts[1:])
        result.lines.append((status, file_part, test_part))
    elif '---' in stripped:
        result.lines.append(('context', '', stripped))


def parse_pytest_output(output: str) -> ParsedTestResult:
    """Parse pytest output into structured test results."""
    result = ParsedTestResult()

    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _is_pytest_summary_line(stripped):
            _apply_pytest_summary_counts(result, stripped)
            break
        _parse_pytest_test_line(result, stripped)

    return result


def _pytest_status_icon(status: str) -> str:
    if status == 'pass':
        return f'[{CLR_STATUS_OK}]\u2713[/{CLR_STATUS_OK}]'
    if status == 'fail':
        return f'[{CLR_STATUS_ERR}]\u2717[/{CLR_STATUS_ERR}]'
    if status == 'skip':
        return f'[{CLR_SECONDARY}]\u25cb[/{CLR_SECONDARY}]'
    return f'[{CLR_SECONDARY}]\u00b7[/{CLR_SECONDARY}]'


def _append_pytest_overflow(output: list[str], total: int) -> None:
    if total > 15:
        output.append(f'  [dim]... {total - 15} more[/dim]')


def _format_pytest_test_lines(result: ParsedTestResult) -> list[str]:
    output: list[str] = []
    if not result.lines:
        return output
    output.append('')
    for status, file_part, test_part in result.lines[:15]:
        icon = _pytest_status_icon(status)
        if file_part:
            output.append(f'  {icon} {_markup_escape(file_part)}')
        if test_part:
            output.append(f'     {_markup_escape(test_part)}')
    _append_pytest_overflow(output, len(result.lines))
    return output


def _append_pytest_duration(parts: list[str], duration: str) -> None:
    if duration:
        parts.append(f'[dim]{_markup_escape(duration)}[/dim]')


def _format_pytest_summary(result: ParsedTestResult) -> list[str]:
    if not result.summary:
        return []
    parts: list[str] = []
    for attr, color, label in _PYTEST_SUMMARY_FORMATS:
        value = getattr(result, attr)
        if value:
            parts.append(f'[{color}]{value} {label}[/{color}]')
    _append_pytest_duration(parts, result.duration)
    if parts:
        return [f'  {" \u00b7 ".join(parts)}']
    return []


def format_pytest_panel(result: ParsedTestResult) -> list[str]:
    """Format pytest results as lines for display."""
    output = _format_pytest_test_lines(result)
    output.extend(_format_pytest_summary(result))
    return output


def _check_git_clean_status(result: ParsedGitStatus, stripped: str) -> None:
    if 'nothing to commit' in stripped or 'working tree clean' in stripped:
        result.clean = True


def _is_git_staged_change(stripped: str) -> bool:
    for keyword in ('new file:', 'modified:', 'deleted:'):
        if keyword in stripped:
            return True
    return False


def _try_parse_git_file_change(result: ParsedGitStatus, stripped: str) -> bool:
    if _is_git_staged_change(stripped):
        result.staged.append(stripped)
        return True
    if stripped.startswith('??'):
        result.untracked.append(stripped[2:].strip())
        return True
    return False


def _has_any_git_changes(result: ParsedGitStatus) -> bool:
    if result.staged:
        return True
    if result.unstaged:
        return True
    if result.untracked:
        return True
    return False


def _parse_git_branch_info(result: ParsedGitStatus, stripped: str) -> None:
    if 'Your branch is ahead' in stripped:
        m = re.search(r'(\d+) commit', stripped)
        if m:
            result.ahead = int(m.group(1))
    elif 'Your branch is behind' in stripped:
        m = re.search(r'(\d+) commit', stripped)
        if m:
            result.behind = int(m.group(1))


def _is_git_header_line(stripped: str) -> bool:
    if stripped.startswith('Changes to be committed'):
        return True
    if stripped.startswith('Untracked files'):
        return True
    return False


def _classify_git_line(result: ParsedGitStatus, stripped: str) -> None:
    if _is_git_header_line(stripped):
        return
    if stripped.startswith('Changes not staged'):
        result.unstaged.append(stripped)
        return
    if _try_parse_git_file_change(result, stripped):
        return
    if _has_any_git_changes(result):
        _parse_git_branch_info(result, stripped)


def _process_git_line(result: ParsedGitStatus, stripped: str) -> None:
    if not stripped:
        return
    _check_git_clean_status(result, stripped)
    _classify_git_line(result, stripped)


def parse_git_status(output: str) -> ParsedGitStatus:
    """Parse git status output."""
    result = ParsedGitStatus()

    for line in output.splitlines():
        _process_git_line(result, line.strip())

    return result


def _append_section_overflow(
    output: list[str], items: list[str], max_items: int
) -> None:
    if len(items) > max_items:
        output.append(f'  [dim]... {len(items) - max_items} more[/dim]')


def _format_git_file_section(
    output: list[str],
    title: str,
    items: list[str],
    title_color: str,
    line_color: str,
    line_prefix: str,
    show_more: bool = True,
) -> None:
    if not items:
        return
    if output:
        output.append('')
    output.append(f'[{title_color}]{title} ({len(items)}):[/{title_color}]')
    for item in items[:5]:
        escaped = _markup_escape(item)
        output.append(f'  [{line_color}]{line_prefix}{escaped}[/{line_color}]')
    if show_more:
        _append_section_overflow(output, items, 5)


def _format_git_clean_line(result: ParsedGitStatus, output: list[str]) -> None:
    if not result.clean:
        return
    if output:
        output.append('')
    output.append(f'[{CLR_STATUS_OK}]\u2713 Working tree clean[/{CLR_STATUS_OK}]')


def format_git_status_panel(result: ParsedGitStatus) -> list[str]:
    """Format git status as lines."""
    output: list[str] = []
    _format_git_file_section(
        output, 'Staged', result.staged, CLR_STATUS_OK, 'green', '+ '
    )
    _format_git_file_section(
        output, 'Changed', result.unstaged, CLR_STATUS_WARN, 'yellow', '~ '
    )
    _format_git_file_section(
        output,
        'Untracked',
        result.untracked,
        CLR_SECONDARY,
        'dim',
        '? ',
        show_more=False,
    )
    _format_git_clean_line(result, output)
    return output


def parse_shell_output(
    command: str, output: str, *, max_lines: int = 50
) -> ShellOutput:
    """Parse shell output into structured format."""
    kind = detect_output_type(command, output)
    lines = output.splitlines()[:max_lines]
    truncated = len(output.splitlines()) > max_lines

    result = ShellOutput(
        kind=kind,
        lines=lines,
        truncated=truncated,
        first_line=lines[0] if lines else '',
    )

    if kind == 'pytest':
        result.parsed_test = parse_pytest_output(output)
    elif kind == 'git_status':
        result.parsed_git_status = parse_git_status(output)
    elif kind == 'ls':
        result.parsed_ls = _parse_ls_output(output)

    return result


def _should_skip_ls_entry(name: str) -> bool:
    if not name:
        return True
    if name in ('.', '..'):
        return True
    return False


def _classify_ls_entry(
    result: ParsedLsOutput, perms: str, name: str, parts: list[str]
) -> None:
    if perms.startswith('d'):
        result.dirs.append(('\U0001f4c1', name))
        return
    size = parts[4] if len(parts) > 4 else ''
    result.files.append(('\U0001f4c4', name, size))


def _parse_ls_output(output: str) -> ParsedLsOutput:
    """Parse ls -la output into files/dirs."""
    result = ParsedLsOutput()

    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 9:
            continue
        perms = parts[0]
        name = ' '.join(parts[8:])
        if _should_skip_ls_entry(name):
            continue
        _classify_ls_entry(result, perms, name, parts)

    return result


def format_generic_output(lines: list[str], max_preview: int = 5) -> list[str]:
    """Format generic text output as preview lines."""
    output: list[str] = []
    for line in lines[:max_preview]:
        stripped = line.strip()
        if stripped:
            output.append(f'  {stripped}')
    return output
