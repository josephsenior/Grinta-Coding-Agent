"""Unified activity renderer for Grinta.

Provides a single rendering pipeline that produces consistent output for both
CLI (Rich) and TUI (Textual) modes. Uses activity cards with badges, verbs,
and structured content instead of heavy bordered panels.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rich.text import Text

from backend.cli._tool_display.renderers.badge import badge_for_tool_name
from backend.cli.theme import (
    NAVY_BRAND,
    NAVY_ERROR,
    NAVY_READY,
    NAVY_TEXT_DIM,
    NAVY_TEXT_MUTED,
    NAVY_WAITING,
)


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences using Rich's parser (handles all ECMA-48 sequences)."""
    if not text:
        return text
    return Text.from_ansi(text).plain


_ERROR_HEAVY_PATTERN = re.compile(
    r'(?im)\b('
    r'error|errors|exception|traceback|failed|failure|panic|fatal|assertionerror|'
    r'validation|invalid|permission denied|not found|syntaxerror|typeerror|'
    r'<<<<<<<|=======|>>>>>>>'
    r')\b'
)


def _looks_error_heavy(text: str | None) -> bool:
    if not text:
        return False
    return bool(_ERROR_HEAVY_PATTERN.search(text))


@dataclass
class ActivityLine:
    """A single line in an activity card."""

    text: str
    style: str = ''
    indent: int = 0


@dataclass
class ActivityCard:
    """A structured activity card for rendering.

    This data structure can be rendered to both Rich (CLI) and Textual (TUI).
    """

    verb: str
    detail: str
    badge_category: str = 'tool'
    title: str | None = None
    secondary: str | None = None
    secondary_kind: str = 'neutral'
    extra_lines: list[ActivityLine] = field(default_factory=list)
    is_collapsible: bool = False
    start_collapsed: bool = False

    _KIND_COLORS = {
        'ok': NAVY_READY,
        'err': NAVY_ERROR,
        'warn': NAVY_WAITING,
        'neutral': NAVY_TEXT_MUTED,
    }

    def to_rich_lines(self) -> list[str]:
        """Convert to Rich markup lines for CLI rendering."""
        lines: list[str] = []

        badge = badge_for_tool_name(self.badge_category)
        badge_render = badge.render()
        verb_style = f'bold {NAVY_BRAND}'
        header = f'{badge_render} [{verb_style}]{self.verb}[/] {self.detail}'

        if self.title:
            lines.append(f'[dim]{self.title}[/dim]')

        lines.append(header)

        if self.secondary:
            color = self._KIND_COLORS.get(self.secondary_kind, NAVY_TEXT_MUTED)
            icon = {
                'ok': '[bold #54efae]✓[/]',
                'err': '[bold #fd8383]✗[/]',
                'warn': '[bold #f6ff8f]⚠[/]',
                'neutral': '[dim #969aad]•[/]',
            }.get(self.secondary_kind, '•')
            lines.append(f'    {icon} [{color}]{self.secondary}[/]')

        for extra in self.extra_lines:
            indent = '  ' * extra.indent
            style = extra.style if extra.style else NAVY_TEXT_MUTED
            lines.append(f'{indent}[{style}]{extra.text}[/]')

        return lines

    def to_tui_markup(self) -> str:
        """Convert to Textual markup for TUI rendering."""
        return '\n'.join(self.to_rich_lines())


class ActivityRenderer:
    """Factory for creating activity cards from agent events."""

    @staticmethod
    def shell_command(
        command: str,
        output: str | None = None,
        exit_code: int | None = None,
        duration: str = '',
    ) -> ActivityCard:
        """Create an activity card for a shell command."""
        cmd_preview = command[:80] + ('...' if len(command) > 80 else '')

        secondary_parts: list[str] = []
        if exit_code is not None:
            secondary_parts.append(f'exit {exit_code}')

        secondary = ' · '.join(secondary_parts) if secondary_parts else None
        kind = (
            'ok'
            if exit_code == 0
            else ('err' if exit_code is not None and exit_code != 0 else 'neutral')
        )

        extra_lines: list[ActivityLine] = []
        if output:
            preview_lines = output.splitlines()[:8]
            for line in preview_lines:
                truncated = line[:120] + ('...' if len(line) > 120 else '')
                extra_lines.append(
                    ActivityLine(truncated, style=NAVY_TEXT_MUTED, indent=1)
                )
            if len(output.splitlines()) > 8:
                extra_lines.append(
                    ActivityLine(
                        f'... {len(output.splitlines()) - 8} more lines',
                        style=NAVY_TEXT_DIM,
                        indent=1,
                    )
                )

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
        )

    @staticmethod
    def file_read(path: str, line_range: str = '') -> ActivityCard:
        """Create an activity card for a file read."""
        detail = f'{path}  [{NAVY_TEXT_DIM}]·  {line_range}[/]' if line_range else path
        return ActivityCard(
            verb='Read',
            detail=detail,
            badge_category='files',
            title='Files',
        )

    @staticmethod
    def file_edit(
        verb: str,
        path: str,
        line_range: str = '',
        added: int = 0,
        removed: int = 0,
        new_file: bool = False,
        diff_lines: list[str] | None = None,
        preview_content: str | None = None,
    ) -> ActivityCard:
        """Create an activity card for a file edit."""
        detail = path
        if line_range:
            detail = f'{path}  [dim]·  {line_range}[/dim]'

        secondary = None
        if added or removed:
            parts = []
            if added:
                parts.append(f'+{added}')
            if removed:
                parts.append(f'-{removed}')
            secondary = ', '.join(parts)

        extra_lines: list[ActivityLine] = []
        if diff_lines:
            for line in diff_lines[:20]:
                stripped = line.rstrip()
                extra_lines.append(ActivityLine(stripped, indent=0))

            if len(diff_lines) > 20:
                extra_lines.append(
                    ActivityLine(
                        f'... {len(diff_lines) - 20} more diff lines',
                        style=NAVY_TEXT_DIM,
                        indent=1,
                    )
                )

        diff_text = '\n'.join(diff_lines or [])
        should_collapse = (
            bool(diff_lines)
            and len(diff_lines or []) > 12
            and not _looks_error_heavy(diff_text)
        )

        return ActivityCard(
            verb=verb,
            detail=detail,
            badge_category='files',
            title='Files',
            secondary=secondary,
            secondary_kind='ok' if added else 'neutral',
            extra_lines=extra_lines,
            is_collapsible=bool(diff_lines),
            start_collapsed=should_collapse,
        )

    @staticmethod
    def file_create(
        path: str,
        line_count: int = 0,
        preview_content: str | None = None,
    ) -> ActivityCard:
        """Create an activity card for file creation."""
        return ActivityRenderer.file_create_with_preview(
            path,
            line_count=line_count,
            preview_content=preview_content,
        )

    @staticmethod
    def file_create_with_preview(
        path: str,
        line_count: int = 0,
        preview_content: str | None = None,
    ) -> ActivityCard:
        """Create an activity card for file creation."""
        secondary = f'+{line_count}' if line_count else None
        extra_lines: list[ActivityLine] = []
        if preview_content:
            lines = preview_content.rstrip('\n').split('\n')
            extra_lines.append(ActivityLine(f'Path: {path}', indent=0))
            extra_lines.append(ActivityLine(f'Added: +{line_count}', indent=0))
            extra_lines.append(ActivityLine('─' * 40, indent=0))
            for line in lines:
                extra_lines.append(ActivityLine(line, indent=0))
        should_collapse = bool(preview_content) and len(preview_content) > 500
        return ActivityCard(
            verb='Created',
            detail=path,
            badge_category='files',
            title='Files',
            secondary=secondary,
            secondary_kind='ok' if secondary else 'neutral',
            extra_lines=extra_lines,
            is_collapsible=bool(preview_content),
            start_collapsed=should_collapse,
        )

    @staticmethod
    def mcp_tool(
        name: str,
        arguments: dict | None = None,
        result: str | None = None,
        success: bool | None = None,
        error: str | None = None,
    ) -> ActivityCard:
        """Create an activity card for an MCP tool call."""
        args_str = ''
        if arguments:
            args_preview = ', '.join(
                f'{k}={repr(v)[:30]}' for k, v in list(arguments.items())[:2]
            )
            if len(args_preview) > 60:
                args_preview = args_preview[:57] + '...'
            args_str = f'({args_preview})' if args_preview else ''

        secondary = None
        secondary_kind = 'neutral'
        if error:
            secondary = 'failed'
            secondary_kind = 'err'
        elif success is True:
            secondary = 'completed'
            secondary_kind = 'ok'

        extra_lines: list[ActivityLine] = []
        if result:
            preview = result[:200] + ('...' if len(result) > 200 else '')
            extra_lines.append(ActivityLine(preview, style=NAVY_TEXT_MUTED, indent=1))

        return ActivityCard(
            verb='Called',
            detail=f'{name}{args_str}',
            badge_category='mcp',
            title='Connected Tool',
            secondary=secondary,
            secondary_kind=secondary_kind,
            extra_lines=extra_lines,
            is_collapsible=bool(result) or bool(error),
            start_collapsed=not bool(error),
        )

    @staticmethod
    def browser_action(
        action_name: str,
        url: str = '',
        result: str | None = None,
        error: str | None = None,
    ) -> ActivityCard:
        """Create an activity card for a browser action."""
        detail = url[:80] if url else action_name

        secondary = None
        secondary_kind = 'neutral'
        if error:
            secondary = 'error' if len(error) > 60 else error
            secondary_kind = 'err'
        elif result:
            secondary = 'done'
            secondary_kind = 'ok'

        extra_lines: list[ActivityLine] = []
        if url:
            extra_lines.append(ActivityLine(f'URL: {url}', indent=0))
        extra_lines.append(ActivityLine(f'Action: {action_name}', indent=0))
        if error:
            extra_lines.append(
                ActivityLine(f'Error: {error}', style=NAVY_ERROR, indent=0)
            )

        return ActivityCard(
            verb=action_name.title(),
            detail=detail,
            badge_category='browser',
            title='Browser',
            secondary=secondary,
            secondary_kind=secondary_kind,
            extra_lines=extra_lines,
            is_collapsible=bool(extra_lines),
            start_collapsed=not bool(error),
        )

    @staticmethod
    def lsp_query(
        symbol: str,
        result: str | None = None,
        available: bool = True,
    ) -> ActivityCard:
        """Create an activity card for an LSP query."""
        secondary = None
        secondary_kind = 'neutral'
        if not available:
            secondary = 'unavailable'
            secondary_kind = 'err'
        elif result:
            secondary = 'completed'
            secondary_kind = 'ok'

        extra_lines: list[ActivityLine] = []
        if result:
            preview = result[:200] + ('...' if len(result) > 200 else '')
            extra_lines.append(ActivityLine(preview, style=NAVY_TEXT_MUTED, indent=1))

        return ActivityCard(
            verb='Analyzed',
            detail=symbol,
            badge_category='code',
            title='Code',
            secondary=secondary,
            secondary_kind=secondary_kind,
            extra_lines=extra_lines,
            is_collapsible=bool(result),
            start_collapsed=bool(result),
        )

    @staticmethod
    def delegation(
        task: str,
        worker: str = '',
        result: str | None = None,
        success: bool | None = None,
    ) -> ActivityCard:
        """Create an activity card for task delegation."""
        task_preview = task[:100] + ('...' if len(task) > 100 else '')

        extra_lines: list[ActivityLine] = []
        if worker:
            extra_lines.append(
                ActivityLine(f'Worker: {worker}', style=NAVY_TEXT_DIM, indent=1)
            )
        if result:
            preview = result[:200] + ('...' if len(result) > 200 else '')
            extra_lines.append(ActivityLine(preview, style=NAVY_TEXT_MUTED, indent=1))

        secondary = None
        secondary_kind = 'neutral'
        if success is True:
            secondary = 'completed'
            secondary_kind = 'ok'
        elif success is False:
            secondary = 'failed'
            secondary_kind = 'err'

        should_collapse = (
            bool(result) and success is not False and not _looks_error_heavy(result)
        )

        return ActivityCard(
            verb='Delegated',
            detail=task_preview,
            badge_category='workers',
            title='Workers',
            secondary=secondary,
            secondary_kind=secondary_kind,
            extra_lines=extra_lines,
            is_collapsible=bool(result),
            start_collapsed=should_collapse,
        )

    @staticmethod
    def terminal_output(
        content: str, session_id: str = '', exit_code: int | None = None
    ) -> ActivityCard:
        """Create an activity card for terminal output."""
        # Strip ANSI escape sequences from PTY/interactive terminal output
        if content:
            content = _strip_ansi(content)

        extra_lines: list[ActivityLine] = []
        if session_id:
            extra_lines.append(
                ActivityLine(f'Session: {session_id}', style=NAVY_TEXT_DIM, indent=1)
            )

        if content:
            lines = content.splitlines()[:15]
            for line in lines:
                truncated = line[:120] + ('...' if len(line) > 120 else '')
                extra_lines.append(
                    ActivityLine(truncated, style=NAVY_TEXT_MUTED, indent=1)
                )
            if len(content.splitlines()) > 15:
                extra_lines.append(
                    ActivityLine(
                        f'... {len(content.splitlines()) - 15} more lines',
                        style=NAVY_TEXT_DIM,
                        indent=1,
                    )
                )

        secondary = None
        kind = 'neutral'
        if exit_code is not None:
            secondary = f'exit {exit_code}'
            kind = 'ok' if exit_code == 0 else 'err'
        elif session_id:
            secondary = f'session {session_id}'

        should_collapse = (
            bool(content) and exit_code == 0 and not _looks_error_heavy(content)
        )

        return ActivityCard(
            verb='Output',
            detail=f'Terminal {session_id}' if session_id else 'Terminal',
            badge_category='terminal',
            title='Terminal',
            secondary=secondary,
            secondary_kind=kind,
            extra_lines=extra_lines,
            is_collapsible=bool(extra_lines),
            start_collapsed=should_collapse,
        )

    @staticmethod
    def terminal_action(
        verb: str,
        detail: str,
        secondary: str | None = None,
        secondary_kind: str = 'neutral',
        extra_content: str | None = None,
    ) -> ActivityCard:
        """Create an activity card for a terminal lifecycle action (start, send, read)."""
        extra_lines: list[ActivityLine] = []
        if extra_content:
            for line in extra_content.splitlines():
                extra_lines.append(ActivityLine(line, style=NAVY_TEXT_MUTED, indent=1))

        return ActivityCard(
            verb=verb,
            detail=detail,
            badge_category='terminal',
            title='Terminal',
            secondary=secondary,
            secondary_kind=secondary_kind,
            extra_lines=extra_lines,
            is_collapsible=bool(extra_lines),
            start_collapsed=bool(extra_lines),
        )

    @staticmethod
    def condensation(count: int = 1, result: str | None = None) -> ActivityCard:
        """Create an activity card for context condensation."""
        suffix = (
            'st'
            if count % 10 == 1 and count % 11 != 1
            else 'nd'
            if count % 10 == 2 and count % 11 != 2
            else 'rd'
            if count % 10 == 3 and count % 11 != 3
            else 'th'
        )
        return ActivityCard(
            verb=f'Compressed ({count}{suffix})',
            detail='context',
            badge_category='tool',
            extra_lines=[ActivityLine(result)] if result else None,
            is_collapsible=bool(result),
            start_collapsed=False,
        )

    @staticmethod
    def user_reject() -> ActivityCard:
        """Create an activity card for user rejection."""
        return ActivityCard(
            verb='Rejected',
            detail='Action rejected by user',
            badge_category='tool',
            secondary_kind='err',
        )

    @staticmethod
    def server_ready(url: str = '', port: str = '') -> ActivityCard:
        """Create an activity card for server ready status."""
        label = url or f'port {port}'
        return ActivityCard(
            verb='Ready',
            detail=f'Server accepting connections · {label}',
            badge_category='tool',
            secondary_kind='ok',
        )

    @staticmethod
    def memory_update(label: str = 'context') -> ActivityCard:
        """Create an activity card for memory/context recall."""
        return ActivityCard(
            verb='Recalled',
            detail=label,
            badge_category='memory',
            title='Memory',
        )

    @staticmethod
    def search_results(
        query: str,
        match_count: int = 0,
        file_count: int = 0,
        file_list: list[tuple[str, int]] | None = None,
        result_lines: list[str] | None = None,
        scope: str = '',
    ) -> ActivityCard:
        """Create an activity card for search results.

        Args:
            query: The search pattern
            match_count: Total number of matches
            file_count: Total number of files with matches
            file_list: List of (filepath, match_count) tuples for display
            result_lines: Raw ripgrep-style result lines (file:line:content)
            scope: Optional search path scope (e.g. 'src/runtime')
        """
        # Detail: quoted query, optionally with scope
        quoted = f'"{query}"'
        detail = f'{quoted} in {scope}' if scope else quoted

        # Secondary: match count · file count
        if match_count and file_count:
            secondary = f'{match_count} matches · {file_count} files'
        elif match_count:
            secondary = f'{match_count} matches'
        else:
            secondary = 'no matches'

        extra_lines: list[ActivityLine] = []

        # Expanded view: grouped by file with line numbers and snippets
        if result_lines:
            from backend.cli._tool_display.renderers.search import (
                render_search_results,
            )

            rich_lines = render_search_results(
                '\n'.join(result_lines),
                query=query,
                max_files=10,
                max_lines_per_file=4,
            )
            for rl in rich_lines:
                extra_lines.append(ActivityLine(rl, indent=0))
        elif file_list:
            for filepath, count in file_list:
                extra_lines.append(
                    ActivityLine(
                        f'• {filepath} ({count} matches)',
                        style=NAVY_TEXT_MUTED,
                        indent=1,
                    )
                )
            total_displayed = len(file_list)
            if file_count > total_displayed:
                remaining_files = file_count - total_displayed
                remaining_matches = match_count - sum(c for _, c in file_list)
                extra_lines.append(
                    ActivityLine(
                        f'... {remaining_files} more files, {remaining_matches} matches',
                        style=NAVY_TEXT_DIM,
                        indent=1,
                    )
                )

        return ActivityCard(
            verb='Search',
            detail=detail,
            badge_category='search',
            title='Search',
            secondary=secondary,
            secondary_kind='ok' if match_count else 'neutral',
            extra_lines=extra_lines,
            is_collapsible=bool(extra_lines),
        )
