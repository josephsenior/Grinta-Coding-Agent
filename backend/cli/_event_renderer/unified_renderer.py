"""Unified activity renderer for Grinta.

Provides a single rendering pipeline that produces consistent output for both
CLI (Rich) and TUI (Textual) modes. Uses activity cards with badges, verbs,
and structured content instead of heavy bordered panels.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pygments.lexers import guess_lexer_for_filename
from pygments.util import ClassNotFound
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


# Maps a search ``source_tool`` value to the (badge_category, title, verb)
# used by the activity card.  Dedicated tools (``grep``, ``glob``) get their
# own categories; anything else (including the legacy generic ``search``
# source) falls back to the unified search card.
_SEARCH_CARD_PRESETS: dict[str, tuple[str, str, str]] = {
    'grep': ('grep', 'Grep', 'Grepped'),
    'glob': ('glob', 'Glob', 'Globbed'),
    'search': ('search', 'Search', 'Searched'),
}


def _extract_search_query(command: str) -> str:
    """Extract the search query/pattern from a grep/glob command."""
    # Try to extract quoted pattern: rg "pattern" or grep 'pattern'
    match = re.search(r'(?:rg|grep)\s+[\'"]([^\'"]+)[\'"]', command)
    if match:
        return match.group(1)

    # Try to extract unquoted pattern: rg pattern or grep pattern
    match = re.search(r'(?:rg|grep)\s+(\S+)', command)
    if match:
        return match.group(1)

    # PowerShell Get-ChildItem with filter
    match = re.search(r'-Filter\s+[\'"]([^\'"]+)[\'"]', command)
    if match:
        return match.group(1)

    # Fallback: return first meaningful argument
    parts = command.split()
    for part in parts[1:]:
        if not part.startswith('-') and part not in ('|', 'rg', 'grep'):
            return part[:50]

    return command[:50]


def _lexer_for_path(path: str) -> str | None:
    """Return a Pygments lexer name for ``path`` based on its extension.

    Determined entirely from the filename — no content is inspected, so the
    result is identical for the same path regardless of body. Returns
    ``None`` for paths with no recognised extension.
    """
    if not path:
        return None
    try:
        lexer = guess_lexer_for_filename(path, '')
    except ClassNotFound:
        return None
    if lexer.name.lower() in {'text', 'text only', 'plain text'}:
        return None
    return lexer.name


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
    syntax_language: str | None = None

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
        if ActivityRenderer._is_grep_shell_command(command):
            return ActivityRenderer._grep_shell_command(command, output, exit_code)
        if ActivityRenderer._is_glob_shell_command(command):
            return ActivityRenderer._glob_shell_command(command, output, exit_code)

        cmd_preview = command[:80] + ('...' if len(command) > 80 else '')
        secondary, kind = ActivityRenderer._build_shell_secondary(exit_code)
        extra_lines = ActivityRenderer._build_shell_output_lines(output)
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
        return ActivityRenderer._build_search_shell_card(
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
        return ActivityRenderer._build_search_shell_card(
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
        match_count, file_count = ActivityRenderer._count_search_matches(result_lines)
        secondary = ActivityRenderer._build_search_secondary(
            match_count, file_count, exit_code
        )
        extra_lines = ActivityRenderer._build_search_extra_lines(result_lines)
        kind = ActivityRenderer._resolve_search_card_kind(exit_code, output)

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

    @staticmethod
    def file_read(path: str, line_range: str = '') -> ActivityCard:
        """Create an activity card for a file read."""
        detail = f'{path}  [{NAVY_WAITING}]{line_range}[/]' if line_range else path
        return ActivityCard(
            verb='Read',
            detail=detail,
            badge_category='files',
            title='Files',
            syntax_language=_lexer_for_path(path),
        )

    @staticmethod
    def _build_edit_secondary(added: int, removed: int) -> str | None:
        if not (added or removed):
            return None
        parts = []
        if added:
            parts.append(f'+{added}')
        if removed:
            parts.append(f'-{removed}')
        return ', '.join(parts)

    @staticmethod
    def _build_diff_extra_lines(diff_lines: list[str] | None) -> list[ActivityLine]:
        extra_lines: list[ActivityLine] = []
        if not diff_lines:
            return extra_lines
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
        return extra_lines

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
        detail = f'{path}  [dim]·  {line_range}[/dim]' if line_range else path
        secondary = ActivityRenderer._build_edit_secondary(added, removed)
        extra_lines = ActivityRenderer._build_diff_extra_lines(diff_lines)
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
            secondary_kind='ok' if added or removed else 'neutral',
            extra_lines=extra_lines,
            is_collapsible=bool(diff_lines),
            start_collapsed=should_collapse,
            syntax_language='diff',
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
        return ActivityCard(
            verb='Created',
            detail=path,
            badge_category='files',
            title='Files',
            secondary=secondary,
            secondary_kind='ok' if secondary else 'neutral',
            syntax_language=_lexer_for_path(path),
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
    def _build_terminal_content_lines(content: str | None) -> list[ActivityLine]:
        extra_lines: list[ActivityLine] = []
        if not content:
            return extra_lines
        lines = content.splitlines()[:15]
        for line in lines:
            truncated = line[:120] + ('...' if len(line) > 120 else '')
            extra_lines.append(ActivityLine(truncated, style=NAVY_TEXT_MUTED, indent=1))
        if len(content.splitlines()) > 15:
            extra_lines.append(
                ActivityLine(
                    f'... {len(content.splitlines()) - 15} more lines',
                    style=NAVY_TEXT_DIM,
                    indent=1,
                )
            )
        return extra_lines

    @staticmethod
    def _build_terminal_secondary(
        exit_code: int | None,
        session_id: str,
    ) -> tuple[str | None, str]:
        if exit_code is not None:
            return f'exit {exit_code}', 'ok' if exit_code == 0 else 'err'
        if session_id:
            return f'session {session_id}', 'neutral'
        return None, 'neutral'

    @staticmethod
    def terminal_output(
        content: str, session_id: str = '', exit_code: int | None = None
    ) -> ActivityCard:
        """Create an activity card for terminal output."""
        if content:
            content = _strip_ansi(content)

        extra_lines: list[ActivityLine] = []
        if session_id:
            extra_lines.append(
                ActivityLine(f'Session: {session_id}', style=NAVY_TEXT_DIM, indent=1)
            )
        extra_lines.extend(ActivityRenderer._build_terminal_content_lines(content))
        secondary, kind = ActivityRenderer._build_terminal_secondary(
            exit_code, session_id
        )
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
            syntax_language='console',
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
            is_collapsible=True,
            start_collapsed=True,
            syntax_language='console',
        )

    @staticmethod
    def condensation(count: int = 1, result: str | None = None) -> ActivityCard:
        """Create an activity card for context condensation."""
        suffix = 'th'
        if count % 100 not in (11, 12, 13):
            suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(count % 10, 'th')
        is_complete = result is not None
        return ActivityCard(
            verb=f'Compacted ({count}{suffix})'
            if is_complete
            else f'Compacting ({count}{suffix})',
            detail='context',
            badge_category='tool',
            extra_lines=[ActivityLine(result)] if result else None,
            secondary='Done' if is_complete else None,
            secondary_kind='ok' if is_complete else 'neutral',
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
    def _build_search_results_secondary(match_count: int, file_count: int) -> str:
        if match_count and file_count:
            return f'{match_count} matches · {file_count} files'
        if match_count:
            return f'{match_count} matches'
        return 'no matches'

    @staticmethod
    def _build_search_results_extra_lines(
        query: str,
        result_lines: list[str] | None,
        file_list: list[tuple[str, int]] | None,
        file_count: int,
        match_count: int,
    ) -> list[ActivityLine]:
        extra_lines: list[ActivityLine] = []
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
            return extra_lines
        if not file_list:
            return extra_lines
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
        return extra_lines

    @staticmethod
    def search_results(
        query: str,
        match_count: int = 0,
        file_count: int = 0,
        file_list: list[tuple[str, int]] | None = None,
        result_lines: list[str] | None = None,
        scope: str = '',
        *,
        source_tool: str = 'search',
    ) -> ActivityCard:
        """Create an activity card for search results.

        Args:
            query: The search pattern
            match_count: Total number of matches
            file_count: Total number of files with matches
            file_list: List of (filepath, match_count) tuples for display
            result_lines: Raw ripgrep-style result lines (file:line:content)
            scope: Optional search path scope (e.g. 'src/runtime')
            source_tool: ``'grep'`` or ``'glob'`` to render as the dedicated
                tool card; anything else renders as the generic ``'search'``
                card.
        """
        badge_category, title, verb = _SEARCH_CARD_PRESETS.get(
            source_tool, _SEARCH_CARD_PRESETS['search']
        )
        quoted = f'"{query}"'
        detail = f'{quoted} in {scope}' if scope else quoted
        secondary = ActivityRenderer._build_search_results_secondary(
            match_count, file_count
        )
        extra_lines = ActivityRenderer._build_search_results_extra_lines(
            query,
            result_lines,
            file_list,
            file_count,
            match_count,
        )

        return ActivityCard(
            verb=verb,
            detail=detail,
            badge_category=badge_category,
            title=title,
            secondary=secondary,
            secondary_kind='ok' if match_count else 'neutral',
            extra_lines=extra_lines,
            is_collapsible=bool(extra_lines),
        )
