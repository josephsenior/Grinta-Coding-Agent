"""Unified activity renderer for Grinta.

Provides a single rendering pipeline that produces consistent output for both
CLI (Rich) and TUI (Textual) modes. Uses activity cards with badges, verbs,
and structured content instead of heavy bordered panels.
"""

from __future__ import annotations

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
            if exit_code == 0:
                secondary_parts.append(f'exit {exit_code}')
            else:
                secondary_parts.append(f'exit {exit_code}')
        if duration:
            secondary_parts.append(duration)

        secondary = ' · '.join(secondary_parts) if secondary_parts else None
        kind = 'ok' if exit_code == 0 else ('err' if exit_code is not None and exit_code != 0 else 'neutral')

        extra_lines: list[ActivityLine] = []
        if output:
            preview_lines = output.splitlines()[:8]
            for line in preview_lines:
                truncated = line[:120] + ('...' if len(line) > 120 else '')
                extra_lines.append(ActivityLine(truncated, style=NAVY_TEXT_MUTED, indent=1))
            if len(output.splitlines()) > 8:
                extra_lines.append(
                    ActivityLine(f'... {len(output.splitlines()) - 8} more lines', style=NAVY_TEXT_DIM, indent=1)
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
        )

    @staticmethod
    def file_read(path: str, line_range: str = '') -> ActivityCard:
        """Create an activity card for a file read."""
        detail = f'{path}  [dim]·  {line_range}[/dim]' if line_range else path
        return ActivityCard(
            verb='Read',
            detail=detail,
            badge_category='files',
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
    ) -> ActivityCard:
        """Create an activity card for a file edit."""
        detail = path
        if new_file and added:
            detail += f'  [bold #54efae]+{added}[/]'
        elif line_range:
            detail = f'{path}  [dim]·  {line_range}[/dim]'

        secondary = None
        if not new_file and (added or removed):
            parts = []
            if added:
                parts.append(f'+{added} lines')
            if removed:
                parts.append(f'-{removed} lines')
            secondary = ', '.join(parts)

        extra_lines: list[ActivityLine] = []
        if diff_lines:
            for line in diff_lines[:20]:
                stripped = line.rstrip()
                if stripped.startswith('+') and not stripped.startswith('+++'):
                    # Green background for additions (subtle, less opaque)
                    extra_lines.append(ActivityLine(stripped, style='#54efae on #0d2e1a', indent=1))
                elif stripped.startswith('-') and not stripped.startswith('---'):
                    # Red background for deletions (subtle, less opaque)
                    extra_lines.append(ActivityLine(stripped, style='#fd8383 on #2e0d0d', indent=1))
                elif stripped.startswith('@@'):
                    extra_lines.append(ActivityLine(stripped, style=NAVY_TEXT_MUTED, indent=1))
                else:
                    extra_lines.append(ActivityLine(stripped, style=NAVY_TEXT_DIM, indent=1))

            if len(diff_lines) > 20:
                extra_lines.append(
                    ActivityLine(f'... {len(diff_lines) - 20} more diff lines', style=NAVY_TEXT_DIM, indent=1)
                )

        return ActivityCard(
            verb=verb,
            detail=detail,
            badge_category='files',
            secondary=secondary,
            secondary_kind='ok' if added else 'neutral',
            extra_lines=extra_lines,
            is_collapsible=bool(diff_lines),
        )

    @staticmethod
    def file_create(path: str, line_count: int = 0) -> ActivityCard:
        """Create an activity card for file creation."""
        detail = path
        if line_count:
            detail += f'  [bold #54efae]+{line_count}[/]'
        return ActivityCard(
            verb='Created',
            detail=detail,
            badge_category='files',
        )

    @staticmethod
    def mcp_tool(name: str, arguments: dict | None = None, result: str | None = None) -> ActivityCard:
        """Create an activity card for an MCP tool call."""
        args_str = ''
        if arguments:
            args_preview = ', '.join(f'{k}={repr(v)[:30]}' for k, v in list(arguments.items())[:2])
            if len(args_preview) > 60:
                args_preview = args_preview[:57] + '...'
            args_str = f'({args_preview})' if args_preview else ''

        extra_lines: list[ActivityLine] = []
        if result:
            preview = result[:200] + ('...' if len(result) > 200 else '')
            extra_lines.append(ActivityLine(preview, style=NAVY_TEXT_MUTED, indent=1))

        return ActivityCard(
            verb='Called',
            detail=f'{name}{args_str}',
            badge_category='mcp',
            title='Connected Tool',
            extra_lines=extra_lines,
            is_collapsible=bool(result),
        )

    @staticmethod
    def browser_action(action_name: str, url: str = '') -> ActivityCard:
        """Create an activity card for a browser action."""
        detail = url[:80] if url else action_name
        return ActivityCard(
            verb=action_name.title(),
            detail=detail,
            badge_category='browser',
            title='Browser',
        )

    @staticmethod
    def lsp_query(symbol: str, result: str | None = None) -> ActivityCard:
        """Create an activity card for an LSP query."""
        extra_lines: list[ActivityLine] = []
        if result:
            preview = result[:200] + ('...' if len(result) > 200 else '')
            extra_lines.append(ActivityLine(preview, style=NAVY_TEXT_MUTED, indent=1))

        return ActivityCard(
            verb='Analyzed',
            detail=symbol,
            badge_category='code',
            title='Code',
            extra_lines=extra_lines,
            is_collapsible=bool(result),
        )

    @staticmethod
    def delegation(task: str, worker: str = '', result: str | None = None) -> ActivityCard:
        """Create an activity card for task delegation."""
        task_preview = task[:100] + ('...' if len(task) > 100 else '')

        extra_lines: list[ActivityLine] = []
        if worker:
            extra_lines.append(ActivityLine(f'Worker: {worker}', style=NAVY_TEXT_DIM, indent=1))
        if result:
            preview = result[:200] + ('...' if len(result) > 200 else '')
            extra_lines.append(ActivityLine(preview, style=NAVY_TEXT_MUTED, indent=1))

        return ActivityCard(
            verb='Delegated',
            detail=task_preview,
            badge_category='workers',
            title='Workers',
            extra_lines=extra_lines,
            is_collapsible=bool(result),
        )

    @staticmethod
    def terminal_output(content: str, session_id: str = '', exit_code: int | None = None) -> ActivityCard:
        """Create an activity card for terminal output."""
        # Strip ANSI escape sequences from PTY/interactive terminal output
        if content:
            content = _strip_ansi(content)

        extra_lines: list[ActivityLine] = []
        if session_id:
            extra_lines.append(ActivityLine(f'Session: {session_id}', style=NAVY_TEXT_DIM, indent=1))

        if content:
            lines = content.splitlines()[:15]
            for line in lines:
                truncated = line[:120] + ('...' if len(line) > 120 else '')
                extra_lines.append(ActivityLine(truncated, style=NAVY_TEXT_MUTED, indent=1))
            if len(content.splitlines()) > 15:
                extra_lines.append(
                    ActivityLine(f'... {len(content.splitlines()) - 15} more lines', style=NAVY_TEXT_DIM, indent=1)
                )

        secondary = None
        kind = 'neutral'
        if exit_code is not None:
            secondary = f'exit {exit_code}'
            kind = 'ok' if exit_code == 0 else 'err'

        return ActivityCard(
            verb='Output',
            detail=f'Terminal {session_id}' if session_id else 'Terminal',
            badge_category='terminal',
            title='Terminal',
            secondary=secondary,
            secondary_kind=kind,
            extra_lines=extra_lines,
            is_collapsible=True,
        )

    @staticmethod
    def condensation(pruned_count: int = 0, count: int = 1) -> ActivityCard:
        """Create an activity card for context condensation."""
        suffix = (
            'st' if count % 10 == 1 and count % 11 != 1
            else 'nd' if count % 10 == 2 and count % 11 != 2
            else 'rd' if count % 10 == 3 and count % 11 != 3
            else 'th'
        )
        detail = f'{pruned_count} events' if pruned_count else 'context'
        return ActivityCard(
            verb=f'Compressed ({count}{suffix})',
            detail=detail,
            badge_category='tool',
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
        result_lines: list[str] | None = None,
    ) -> ActivityCard:
        """Create an activity card for search results."""
        secondary = f'{match_count} matches' if match_count else 'No matches'
        extra_lines: list[ActivityLine] = []

        if result_lines:
            for line in result_lines:
                extra_lines.append(ActivityLine(line, style=NAVY_TEXT_MUTED, indent=1))

        return ActivityCard(
            verb='Searched',
            detail=query,
            badge_category='search',
            title='Search',
            secondary=secondary,
            secondary_kind='ok' if match_count else 'neutral',
            extra_lines=extra_lines,
            is_collapsible=bool(result_lines),
        )
