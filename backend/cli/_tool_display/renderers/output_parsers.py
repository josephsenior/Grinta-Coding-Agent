"""Smart output parsing for shell command results.

Detects output type and parses it into structured, visually appealing display.
Supports: pytest, git, npm/yarn/pip, ls, find, curl, and generic text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

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


def detect_output_type(command: str, output: str) -> str:
    """Guess the output type from command + output patterns."""
    cmd_lower = command.lower()
    out_lower = output.lower()

    if 'pytest' in cmd_lower or 'python -m pytest' in cmd_lower:
        return 'pytest'
    if 'coverage' in cmd_lower:
        return 'coverage'
    if cmd_lower.startswith('git status'):
        return 'git_status'
    if cmd_lower.startswith('git diff'):
        return 'git_diff'
    if cmd_lower.startswith('git log'):
        return 'git_log'
    if cmd_lower.startswith('git branch'):
        return 'git_branch'
    if cmd_lower.startswith('npm ') and ('install' in cmd_lower or 'i' in cmd_lower):
        return 'npm_install'
    if cmd_lower.startswith('yarn ') and 'install' in cmd_lower:
        return 'yarn_install'
    if cmd_lower.startswith('pip install') or cmd_lower.startswith('pip3 install'):
        return 'pip_install'
    if cmd_lower.startswith('curl '):
        return 'curl'
    if cmd_lower.startswith('ls ') or cmd_lower == 'ls':
        return 'ls'
    if cmd_lower.startswith('find '):
        return 'find'
    if cmd_lower.startswith('ping '):
        return 'ping'
    if 'ruff' in cmd_lower or 'flake8' in cmd_lower or 'mypy' in cmd_lower:
        return 'linter'
    if out_lower.startswith('usage:'):
        return 'help'
    return 'plain'


def parse_pytest_output(output: str) -> ParsedTestResult:
    """Parse pytest output into structured test results."""
    result = ParsedTestResult()
    lines = output.splitlines()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if ' passed' in stripped or ' failed' in stripped or ' error' in stripped or ' skipped' in stripped:
            m = re.search(r'(\d+) passed', stripped)
            if m:
                result.passed = int(m.group(1))
            m = re.search(r'(\d+) failed', stripped)
            if m:
                result.failed = int(m.group(1))
                result.has_failures = True
            m = re.search(r'(\d+) error', stripped)
            if m:
                result.errors = int(m.group(1))
            m = re.search(r'(\d+) skipped', stripped)
            if m:
                result.skipped = int(m.group(1))
            m = re.search(r'[\d.]+s', stripped)
            if m:
                result.duration = m.group()
            result.summary = stripped
            break

        if '::test_' in stripped or '---' in stripped:
            status = 'pass'
            if 'FAILED' in stripped:
                status = 'fail'
            elif 'SKIPPED' in stripped:
                status = 'skip'
            elif 'PASSED' in stripped:
                status = 'pass'

            parts = stripped.split('::')
            if len(parts) >= 2:
                file_part = parts[0].strip()
                test_part = '::'.join(parts[1:])
                result.lines.append((status, file_part, test_part))
            elif '---' in stripped:
                result.lines.append(('context', '', stripped))

    return result


def format_pytest_panel(result: ParsedTestResult) -> list[str]:
    """Format pytest results as lines for display."""
    output: list[str] = []

    if result.lines:
        output.append('')
        for status, file_part, test_part in result.lines[:15]:
            if status == 'pass':
                icon = f'[{CLR_STATUS_OK}]✓[/{CLR_STATUS_OK}]'
            elif status == 'fail':
                icon = f'[{CLR_STATUS_ERR}]✗[/{CLR_STATUS_ERR}]'
            elif status == 'skip':
                icon = f'[{CLR_SECONDARY}]○[/{CLR_SECONDARY}]'
            else:
                icon = f'[{CLR_SECONDARY}]·[/{CLR_SECONDARY}]'

            if file_part:
                # Escape file_part to prevent MarkupError
                from rich.markup import escape as markup_escape
                escaped_file = markup_escape(file_part)
                output.append(f'  {icon} {escaped_file}')
            if test_part:
                # Escape test_part to prevent MarkupError
                from rich.markup import escape as markup_escape
                escaped_test = markup_escape(test_part)
                output.append(f'     {escaped_test}')

        if len(result.lines) > 15:
            output.append(f'  [dim]... {len(result.lines) - 15} more[/dim]')

    if result.summary:
        parts = []
        if result.passed:
            parts.append(f'[{CLR_STATUS_OK}]{result.passed} passed[/{CLR_STATUS_OK}]')
        if result.failed:
            parts.append(f'[{CLR_STATUS_ERR}]{result.failed} failed[/{CLR_STATUS_ERR}]')
        if result.skipped:
            parts.append(f'[{CLR_SECONDARY}]{result.skipped} skipped[/{CLR_SECONDARY}]')
        if result.duration:
            # Escape duration to prevent MarkupError
            from rich.markup import escape as markup_escape
            escaped_duration = markup_escape(result.duration)
            parts.append(f'[dim]{escaped_duration}[/dim]')
        if parts:
            output.append(f"  {' · '.join(parts)}")

    return output


def parse_git_status(output: str) -> ParsedGitStatus:
    """Parse git status output."""
    result = ParsedGitStatus()
    lines = output.splitlines()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('Changes to be committed'):
            continue
        if stripped.startswith('Changes not staged'):
            result.unstaged.append(stripped)
        elif stripped.startswith('Untracked files'):
            continue
        elif 'new file:' in stripped or 'modified:' in stripped or 'deleted:' in stripped:
            result.staged.append(stripped)
        elif stripped.startswith('??'):
            result.untracked.append(stripped[2:].strip())
        elif result.staged or result.unstaged or result.untracked:
            if 'Your branch is ahead' in stripped:
                m = re.search(r'(\d+) commit', stripped)
                if m:
                    result.ahead = int(m.group(1))
            elif 'Your branch is behind' in stripped:
                m = re.search(r'(\d+) commit', stripped)
                if m:
                    result.behind = int(m.group(1))
        if 'nothing to commit' in stripped or 'working tree clean' in stripped:
            result.clean = True

    return result


def format_git_status_panel(result: ParsedGitStatus) -> list[str]:
    """Format git status as lines."""
    from rich.markup import escape as markup_escape

    output: list[str] = []

    if result.staged:
        output.append(f'[{CLR_STATUS_OK}]Staged ({len(result.staged)}):[/{CLR_STATUS_OK}]')
        for item in result.staged[:5]:
            # Escape item to prevent MarkupError
            escaped_item = markup_escape(item)
            output.append(f'  [green]+ {escaped_item}[/green]')
        if len(result.staged) > 5:
            output.append(f'  [dim]... {len(result.staged) - 5} more[/dim]')

    if result.unstaged:
        if output:
            output.append('')
        output.append(f'[{CLR_STATUS_WARN}]Changed ({len(result.unstaged)}):[/{CLR_STATUS_WARN}]')
        for item in result.unstaged[:5]:
            # Escape item to prevent MarkupError
            escaped_item = markup_escape(item)
            output.append(f'  [yellow]~ {escaped_item}[/yellow]')
        if len(result.unstaged) > 5:
            output.append(f'  [dim]... {len(result.unstaged) - 5} more[/dim]')

    if result.untracked:
        if output:
            output.append('')
        output.append(f'[{CLR_SECONDARY}]Untracked ({len(result.untracked)}):[/{CLR_SECONDARY}]')
        for item in result.untracked[:5]:
            # Escape item to prevent MarkupError
            escaped_item = markup_escape(item)
            output.append(f'  [dim]? {escaped_item}[/dim]')

    if result.clean:
        if output:
            output.append('')
        output.append(f'[{CLR_STATUS_OK}]✓ Working tree clean[/{CLR_STATUS_OK}]')

    return output


def parse_shell_output(command: str, output: str, *, max_lines: int = 50) -> ShellOutput:
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


def _parse_ls_output(output: str) -> ParsedLsOutput:
    """Parse ls -la output into files/dirs."""
    result = ParsedLsOutput()
    lines = output.splitlines()

    for line in lines:
        parts = line.split()
        if len(parts) < 9:
            continue
        perms = parts[0]
        name = ' '.join(parts[8:]) if len(parts) > 8 else ''

        if not name or name in ('.', '..'):
            continue

        if perms.startswith('d'):
            result.dirs.append(('📁', name))
        else:
            size = parts[4] if len(parts) > 4 else ''
            result.files.append(('📄', name, size))

    return result


def format_generic_output(lines: list[str], max_preview: int = 5) -> list[str]:
    """Format generic text output as preview lines."""
    output: list[str] = []
    for line in lines[:max_preview]:
        stripped = line.strip()
        if stripped:
            output.append(f'  {stripped}')
    return output
