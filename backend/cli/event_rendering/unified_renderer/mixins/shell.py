"""Activity card builders — shell domain."""

from __future__ import annotations

import re

from backend.cli.event_rendering.unified_renderer.types import ActivityCard, ActivityLine
from backend.cli.event_rendering.unified_renderer.utils import (
    _SEARCH_CARD_PRESETS,
    _extract_search_query,
    _looks_error_heavy,
)
from backend.cli.theme import NAVY_TEXT_DIM, NAVY_TEXT_MUTED


class _ShellMixin:
    @staticmethod
    def _build_shell_secondary(exit_code: int | None) -> tuple[str | None, str]:
        secondary_parts: list[str] = []
        if exit_code is not None:
            secondary_parts.append(f'exit {exit_code}')
        secondary = ' · '.join(secondary_parts) if secondary_parts else None
        kind = (
            'ok'
            if exit_code == 0
            else ('err' if exit_code is not None and exit_code != 0 else 'neutral')
        )
        return secondary, kind

    @staticmethod
    def _build_shell_output_lines(output: str | None) -> list[ActivityLine]:
        extra_lines: list[ActivityLine] = []
        if not output:
            return extra_lines
        preview_lines = output.splitlines()[:8]
        for line in preview_lines:
            truncated = line[:120] + ('...' if len(line) > 120 else '')
            extra_lines.append(ActivityLine(truncated, style=NAVY_TEXT_MUTED, indent=1))
        if len(output.splitlines()) > 8:
            extra_lines.append(
                ActivityLine(
                    f'... {len(output.splitlines()) - 8} more lines',
                    style=NAVY_TEXT_DIM,
                    indent=1,
                )
            )
        return extra_lines

    @staticmethod
    def shell_command(
        command: str,
        output: str | None = None,
        exit_code: int | None = None,
        duration: str = '',
    ) -> ActivityCard:
        """Create an activity card for a shell command."""
        if _ShellMixin._is_grep_shell_command(command):
            return _ShellMixin._grep_shell_command(command, output, exit_code)
        if _ShellMixin._is_glob_shell_command(command):
            return _ShellMixin._glob_shell_command(command, output, exit_code)

        cmd_preview = command[:80] + ('...' if len(command) > 80 else '')
        secondary, kind = _ShellMixin._build_shell_secondary(exit_code)
        extra_lines = _ShellMixin._build_shell_output_lines(output)
        should_collapse = (
            bool(output) and exit_code == 0 and not _looks_error_heavy(output)
        )

        return ActivityCard(
            verb='Ran',
            detail=f'$ {cmd_preview}',
            badge_category='shell',
            title='Shell',
            secondary=secondary,
            secondary_kind=kind,
            extra_lines=extra_lines,
            is_collapsible=bool(output),
            start_collapsed=should_collapse,
            syntax_language='console',
        )

    @staticmethod
    def _is_grep_shell_command(command: str) -> bool:
        """Detect shell invocations of ripgrep / grep."""
        cmd_lower = command.lower().lstrip()
        return (
            cmd_lower.startswith('rg ')
            or cmd_lower.startswith('rg\t')
            or cmd_lower.startswith('grep ')
            or cmd_lower.startswith('grep-')
            or cmd_lower.startswith('grep\t')
            or ' | rg ' in cmd_lower
            or ' | rg\t' in cmd_lower
            or ' | grep ' in cmd_lower
            or ' | grep\t' in cmd_lower
        )

    @staticmethod
    def _is_glob_shell_command(command: str) -> bool:
        """Detect shell invocations of filesystem globbing."""
        cmd_lower = command.lower().lstrip()
        return (
            cmd_lower.startswith('get-childitem')  # PowerShell
            or cmd_lower.startswith('gci ')  # PowerShell alias
            or cmd_lower.startswith('gci\t')
            or cmd_lower.startswith('find ')  # POSIX -name
            or cmd_lower.startswith('find\t')
        )

    @staticmethod
    def _grep_shell_command(
        command: str,
        output: str | None = None,
        exit_code: int | None = None,
    ) -> ActivityCard:
        """Create a Grep activity card for a shell-level grep invocation."""
        return _ShellMixin._build_search_shell_card(
            command=command,
            output=output,
            exit_code=exit_code,
            source_tool='grep',
        )

    @staticmethod
    def _glob_shell_command(
        command: str,
        output: str | None = None,
        exit_code: int | None = None,
    ) -> ActivityCard:
        """Create a Glob activity card for a shell-level glob invocation."""
        return _ShellMixin._build_search_shell_card(
            command=command,
            output=output,
            exit_code=exit_code,
            source_tool='glob',
        )

    @staticmethod
    def _count_search_matches(result_lines: list[str]) -> tuple[int, int]:
        match_count = 0
        files: set[str] = set()
        for line in result_lines:
            if re.match(r'^[^:]+:\d+:', line):
                match_count += 1
            match = re.match(r'^([^:]+):\d+:', line)
            if match:
                files.add(match.group(1))
        return match_count, len(files)

    @staticmethod
    def _build_search_secondary(
        match_count: int,
        file_count: int,
        exit_code: int | None,
    ) -> str | None:
        if match_count and file_count:
            return f'{match_count} matches · {file_count} files'
        if match_count:
            return f'{match_count} matches'
        if exit_code == 1:
            return 'no matches'
        return None

    @staticmethod
    def _build_search_extra_lines(result_lines: list[str]) -> list[ActivityLine]:
        extra_lines: list[ActivityLine] = []
        if not result_lines:
            return extra_lines
        for line in result_lines[:8]:
            truncated = line[:120] + ('...' if len(line) > 120 else '')
            extra_lines.append(ActivityLine(truncated, style=NAVY_TEXT_MUTED, indent=1))
        if len(result_lines) > 8:
            extra_lines.append(
                ActivityLine(
                    f'... {len(result_lines) - 8} more lines',
                    style=NAVY_TEXT_DIM,
                    indent=1,
                )
            )
        return extra_lines

    @staticmethod
    def _resolve_search_card_kind(
        exit_code: int | None,
        output: str | None,
    ) -> str:
        if exit_code == 0 or (exit_code == 1 and not output):
            return 'ok'
        if exit_code is not None and exit_code > 1:
            return 'err'
        return 'neutral'

    @staticmethod
    def _build_search_shell_card(
        *,
        command: str,
        output: str | None,
        exit_code: int | None,
        source_tool: str,
    ) -> ActivityCard:
        """Shared rendering for shell-level grep/glob invocations."""
        query = _extract_search_query(command) or command[:50]
        result_lines: list[str] = output.splitlines() if output else []
        match_count, file_count = _ShellMixin._count_search_matches(result_lines)
        secondary = _ShellMixin._build_search_secondary(
            match_count, file_count, exit_code
        )
        extra_lines = _ShellMixin._build_search_extra_lines(result_lines)
        kind = _ShellMixin._resolve_search_card_kind(exit_code, output)

        badge_category, title, verb = _SEARCH_CARD_PRESETS[source_tool]
        return ActivityCard(
            verb=verb,
            detail=f'"{query}"',
            badge_category=badge_category,
            title=title,
            secondary=secondary,
            secondary_kind=kind if match_count else 'neutral',
            extra_lines=extra_lines,
            is_collapsible=bool(extra_lines),
            start_collapsed=bool(output) and exit_code == 0,
        )
