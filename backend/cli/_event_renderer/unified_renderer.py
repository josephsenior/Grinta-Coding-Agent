"""Unified activity renderer for Grinta.

Provides a single rendering pipeline that produces consistent output for both
CLI (Rich) and TUI (Textual) modes. Uses activity cards with badges, verbs,
and structured content instead of heavy bordered panels.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from pygments.lexers import guess_lexer_for_filename
from pygments.util import ClassNotFound
from rich.text import Text

from backend.cli._tool_display.preview import mcp_result_user_preview
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
    'find_symbols': ('find_symbols', 'Find Symbols', 'Found'),
    'read_symbols': ('read_symbols', 'Read Symbols', 'Read'),
    'analyze': ('analyze', 'Analyze', 'Analyzed'),
}

_WEB_MCP_KINDS: dict[str, str] = {
    'web_search_exa': 'web_search',
    'web_fetch_exa': 'web_fetch',
    '__native_web_fetch__': 'web_fetch',
    'fetch': 'web_fetch',
}

_WEB_CARD_PRESETS: dict[str, tuple[str, str, str]] = {
    'web_search': ('web_search', 'Web Search', 'Searched'),
    'web_fetch': ('web_fetch', 'Web Fetch', 'Fetched'),
}

_BROWSER_OUTCOMES: dict[str, str] = {
    'navigate': 'loaded',
    'screenshot': 'captured',
    'snapshot': 'ready',
    'click': 'clicked',
    'type': 'typed',
    'browse': 'done',
    'start': 'started',
    'close': 'closed',
}


def _exploration_meta_line(tokens: list[str]) -> list[str]:
    """Return a single meta row line when any tokens are present."""
    cleaned = [token for token in tokens if token]
    if not cleaned:
        return []
    return [' · '.join(cleaned)]


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
    meta_lines: list[str] = field(default_factory=list)
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
    def resolve_native_web_tool_kind(mcp_name: str) -> str | None:
        return _WEB_MCP_KINDS.get((mcp_name or '').strip())

    @staticmethod
    def _coerce_mcp_result_payload(content: str) -> Any:
        s = (content or '').strip()
        if not s:
            return None
        if s.startswith('{') or s.startswith('['):
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                return s
        return s

    @staticmethod
    def _count_collection_in_mcp_content(content: str) -> int:
        payload = ActivityRenderer._coerce_mcp_result_payload(content)
        if isinstance(payload, list):
            return len(payload)
        if not isinstance(payload, dict):
            return 0
        for key in ('results', 'items', 'documents', 'matches'):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
        blocks = payload.get('content')
        if not isinstance(blocks, list):
            return 0
        total = 0
        for block in blocks:
            if not isinstance(block, dict):
                continue
            raw = block.get('text')
            if not isinstance(raw, str) or not raw.strip():
                continue
            inner = raw.strip()
            if not (inner.startswith('{') or inner.startswith('[')):
                continue
            try:
                parsed = json.loads(inner)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, list):
                total += len(parsed)
            elif isinstance(parsed, dict):
                for key in ('results', 'items', 'documents', 'matches'):
                    value = parsed.get(key)
                    if isinstance(value, list):
                        total += len(value)
        return total

    @staticmethod
    def _build_mcp_extra_lines_from_content(content: str) -> list[ActivityLine]:
        from backend.cli._tool_display.renderers.mcp import _format_mcp_result

        payload = ActivityRenderer._coerce_mcp_result_payload(content)
        if payload is None:
            return []
        formatted = _format_mcp_result(payload)
        extra_lines: list[ActivityLine] = []
        for line in formatted[:12]:
            extra_lines.append(
                ActivityLine(str(line), style=NAVY_TEXT_MUTED, indent=1)
            )
        if len(formatted) > 12:
            extra_lines.append(
                ActivityLine(
                    f'... {len(formatted) - 12} more lines',
                    style=NAVY_TEXT_DIM,
                    indent=1,
                )
            )
        if extra_lines:
            return extra_lines
        preview = mcp_result_user_preview(content)
        if preview:
            extra_lines.append(
                ActivityLine(preview, style=NAVY_TEXT_MUTED, indent=1)
            )
        return extra_lines

    @staticmethod
    def _web_tool_secondary(
        kind: str,
        content: str,
        *,
        error: str | None = None,
    ) -> tuple[str, str]:
        if error:
            return 'failed', 'err'
        count = ActivityRenderer._count_collection_in_mcp_content(content)
        if kind == 'web_search':
            if count:
                label = 'result' if count == 1 else 'results'
                return f'{count} {label}', 'ok'
            preview = mcp_result_user_preview(content)
            if preview:
                return preview[:80], 'ok'
            return 'no results', 'neutral'
        if kind == 'web_fetch':
            if count:
                label = 'page' if count == 1 else 'pages'
                return f'{count} {label}', 'ok'
            preview = mcp_result_user_preview(content)
            if preview:
                return preview[:80], 'ok'
            return 'no content', 'neutral'
        return 'completed', 'ok'

    @staticmethod
    def _web_search_meta(arguments: dict[str, Any] | None) -> list[str]:
        tokens: list[str] = []
        args = arguments or {}
        num_results = args.get('numResults')
        if num_results is not None:
            tokens.append(f'limit: {num_results}')
        return _exploration_meta_line(tokens)

    @staticmethod
    def _web_fetch_meta(
        arguments: dict[str, Any] | None,
        content: str = '',
    ) -> list[str]:
        tokens: list[str] = []
        args = arguments or {}
        max_chars = args.get('max_characters')
        if max_chars is not None:
            tokens.append(f'max: {max_chars}')
        payload = ActivityRenderer._coerce_mcp_result_payload(content)
        if isinstance(payload, dict):
            backend = payload.get('backend')
            if isinstance(backend, str) and backend:
                tokens.append(f'backend: {backend}')
        return _exploration_meta_line(tokens)

    @staticmethod
    def web_search_card(
        arguments: dict[str, Any] | None = None,
        *,
        result: str | None = None,
        error: str | None = None,
    ) -> ActivityCard:
        badge_category, title, verb = _WEB_CARD_PRESETS['web_search']
        query = str((arguments or {}).get('query') or '').strip()
        detail = f'"{query}"' if query else 'web'
        secondary, secondary_kind = ActivityRenderer._web_tool_secondary(
            'web_search',
            result or '',
            error=error,
        )
        extra_lines = ActivityRenderer._build_mcp_extra_lines_from_content(
            result or error or ''
        )
        return ActivityCard(
            verb=verb,
            detail=detail,
            badge_category=badge_category,
            title=title,
            secondary=secondary,
            secondary_kind=secondary_kind,
            extra_lines=extra_lines,
            meta_lines=ActivityRenderer._web_search_meta(arguments),
            is_collapsible=bool(extra_lines),
        )

    @staticmethod
    def web_fetch_card(
        arguments: dict[str, Any] | None = None,
        *,
        result: str | None = None,
        error: str | None = None,
    ) -> ActivityCard:
        badge_category, title, verb = _WEB_CARD_PRESETS['web_fetch']
        urls = (arguments or {}).get('urls') or []
        if isinstance(urls, str):
            urls = [urls] if urls.strip() else []
        if len(urls) == 1:
            detail = str(urls[0])[:80]
        elif urls:
            detail = f'{len(urls)} URLs'
        else:
            detail = 'web pages'
        secondary, secondary_kind = ActivityRenderer._web_tool_secondary(
            'web_fetch',
            result or '',
            error=error,
        )
        extra_lines = ActivityRenderer._build_mcp_extra_lines_from_content(
            result or error or ''
        )
        return ActivityCard(
            verb=verb,
            detail=detail,
            badge_category=badge_category,
            title=title,
            secondary=secondary,
            secondary_kind=secondary_kind,
            extra_lines=extra_lines,
            meta_lines=ActivityRenderer._web_fetch_meta(arguments, result or ''),
            is_collapsible=bool(extra_lines),
        )

    @staticmethod
    def mcp_activity_card(
        name: str,
        arguments: dict | None = None,
        *,
        result: str | None = None,
        success: bool | None = None,
        error: str | None = None,
    ) -> ActivityCard:
        """Build the best activity card for an MCP invocation."""
        kind = ActivityRenderer.resolve_native_web_tool_kind(name)
        if kind == 'web_search':
            return ActivityRenderer.web_search_card(
                arguments,
                result=result,
                error=error,
            )
        if kind == 'web_fetch':
            return ActivityRenderer.web_fetch_card(
                arguments,
                result=result,
                error=error,
            )
        return ActivityRenderer.mcp_tool(
            name,
            arguments,
            result=result,
            success=success,
            error=error,
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
        elif result:
            preview = mcp_result_user_preview(result)
            secondary = (preview[:80] if preview else 'completed') or 'completed'
            secondary_kind = 'ok' if success is not False else 'err'
        elif success is True:
            secondary = 'completed'
            secondary_kind = 'ok'

        extra_lines = ActivityRenderer._build_mcp_extra_lines_from_content(
            result or error or ''
        )

        return ActivityCard(
            verb='Called',
            detail=f'{name}{args_str}',
            badge_category='mcp',
            title='Connected Tool',
            secondary=secondary,
            secondary_kind=secondary_kind,
            extra_lines=extra_lines,
            is_collapsible=bool(extra_lines) or bool(error),
            start_collapsed=not bool(error),
        )

    @staticmethod
    def browser_action(
        action_name: str,
        url: str = '',
        result: str | None = None,
        error: str | None = None,
        *,
        image_path: str = '',
    ) -> ActivityCard:
        """Create an activity card for a browser action."""
        from backend.cli._tool_display.renderers.browser import (
            render_browser_navigation,
            render_browser_page,
        )

        action_key = (action_name or 'browser').strip().lower()
        detail = url[:80] if url else action_name

        secondary = None
        secondary_kind = 'neutral'
        if error:
            secondary = 'error' if len(error) > 60 else error
            secondary_kind = 'err'
        elif result:
            secondary = _BROWSER_OUTCOMES.get(action_key, 'done')
            secondary_kind = 'ok'

        extra_lines: list[ActivityLine] = []
        if result and action_key in {'screenshot', 'snapshot', 'browse'}:
            rich_lines = render_browser_page(
                url,
                content_preview=result,
            )
        else:
            rich_lines = render_browser_navigation(action_key, url)
        for line in rich_lines[1:]:
            extra_lines.append(ActivityLine(str(line), indent=0))
        if image_path:
            extra_lines.append(
                ActivityLine(f'Screenshot: {image_path}', style=NAVY_TEXT_DIM, indent=0)
            )
        if error:
            extra_lines.append(
                ActivityLine(f'Error: {error}', style=NAVY_ERROR, indent=0)
            )

        meta_tokens: list[str] = []
        if url:
            meta_tokens.append(f'url: {url[:60]}')
        if image_path:
            meta_tokens.append('screenshot saved')

        return ActivityCard(
            verb=action_name.title(),
            detail=detail,
            badge_category='browser',
            title='Browser',
            secondary=secondary,
            secondary_kind=secondary_kind,
            extra_lines=extra_lines,
            meta_lines=_exploration_meta_line(meta_tokens),
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
    def format_extra_lines(extra_lines: list[ActivityLine]) -> str | None:
        """Join activity card extra lines into TUI/Rich markup text."""
        if not extra_lines:
            return None
        parts: list[str] = []
        for extra in extra_lines:
            indent = '  ' * extra.indent
            parts.append(f'{indent}{extra.text}')
        return '\n'.join(parts)

    @staticmethod
    def _build_search_results_secondary(
        match_count: int,
        file_count: int,
        *,
        source_tool: str = 'search',
        output_mode: str | None = None,
    ) -> str:
        if source_tool == 'glob':
            if file_count == 1:
                return '1 file'
            if file_count:
                return f'{file_count} files'
            return 'no files'
        if source_tool == 'find_symbols':
            if match_count == 1:
                suffix = f' · {file_count} files' if file_count else ''
                return f'1 symbol{suffix}'
            if match_count:
                suffix = f' · {file_count} files' if file_count else ''
                return f'{match_count} symbols{suffix}'
            return 'no symbols'
        if source_tool == 'grep' and output_mode == 'files_with_matches':
            if file_count == 1:
                return '1 file'
            if file_count:
                return f'{file_count} files'
            return 'no files'
        if source_tool == 'grep' and output_mode == 'count':
            if match_count:
                return f'{match_count} total matches'
            return 'no matches'
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
        *,
        source_tool: str = 'search',
    ) -> list[ActivityLine]:
        extra_lines: list[ActivityLine] = []
        if result_lines and source_tool not in {'glob', 'find_symbols'}:
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
        if result_lines and source_tool == 'find_symbols':
            for line in result_lines[:10]:
                extra_lines.append(
                    ActivityLine(
                        f'• {line}',
                        style=NAVY_TEXT_MUTED,
                        indent=1,
                    )
                )
            if len(result_lines) > 10:
                extra_lines.append(
                    ActivityLine(
                        f'... {len(result_lines) - 10} more symbols',
                        style=NAVY_TEXT_DIM,
                        indent=1,
                    )
                )
            return extra_lines
        if not file_list:
            return extra_lines
        max_displayed = 10
        if source_tool == 'glob':
            for filepath, _count in file_list[:max_displayed]:
                extra_lines.append(
                    ActivityLine(
                        f'• {filepath}',
                        style=NAVY_TEXT_MUTED,
                        indent=1,
                    )
                )
            total_displayed = len(file_list[:max_displayed])
            if file_count > total_displayed:
                remaining_files = file_count - total_displayed
                extra_lines.append(
                    ActivityLine(
                        f'... {remaining_files} more files',
                        style=NAVY_TEXT_DIM,
                        indent=1,
                    )
                )
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
        detail: str | None = None,
        meta_lines: list[str] | None = None,
        output_mode: str | None = None,
    ) -> ActivityCard:
        """Create an activity card for search results.

        Args:
            query: The search pattern
            match_count: Total number of matches
            file_count: Total number of files with matches
            file_list: List of (filepath, match_count) tuples for display
            result_lines: Raw ripgrep-style result lines (file:line:content)
            scope: Optional search path scope (e.g. 'src/runtime')
            source_tool: Tool-specific card preset (``grep``, ``glob``, etc.)
            detail: Optional override for the collapsed detail text
            meta_lines: Optional metadata shown in the expanded card footer
            output_mode: Grep output mode for tailored collapsed summaries
        """
        badge_category, title, verb = _SEARCH_CARD_PRESETS.get(
            source_tool, _SEARCH_CARD_PRESETS['search']
        )
        if detail is None:
            quoted = f'"{query}"'
            detail = f'{quoted} in {scope}' if scope else quoted
        secondary = ActivityRenderer._build_search_results_secondary(
            match_count,
            file_count,
            source_tool=source_tool,
            output_mode=output_mode,
        )
        extra_lines = ActivityRenderer._build_search_results_extra_lines(
            query,
            result_lines,
            file_list,
            file_count,
            match_count,
            source_tool=source_tool,
        )
        has_results = bool(match_count or file_count)

        return ActivityCard(
            verb=verb,
            detail=detail,
            badge_category=badge_category,
            title=title,
            secondary=secondary,
            secondary_kind='ok' if has_results else 'neutral',
            extra_lines=extra_lines,
            meta_lines=list(meta_lines or []),
            is_collapsible=bool(extra_lines),
        )

    @staticmethod
    def _build_read_symbols_secondary(
        results: list[dict[str, object]],
    ) -> str:
        if not results:
            return 'no symbols'
        statuses: dict[str, int] = {}
        for item in results:
            status = str(item.get('status') or 'unknown')
            statuses[status] = statuses.get(status, 0) + 1
        if len(statuses) == 1:
            status, count = next(iter(statuses.items()))
            label = 'symbol' if count == 1 else 'symbols'
            return f'{count} {status} {label}'
        parts = [f'{count} {status}' for status, count in sorted(statuses.items())]
        return ' · '.join(parts)

    @staticmethod
    def _build_read_symbols_extra_lines(
        results: list[dict[str, object]],
    ) -> list[ActivityLine]:
        extra_lines: list[ActivityLine] = []
        for item in results[:8]:
            status = str(item.get('status') or 'unknown')
            target = str(
                item.get('qualified_name')
                or item.get('symbol_name')
                or item.get('target')
                or item.get('name')
                or ''
            ).strip()
            path = str(item.get('path') or '').strip()
            if target and path:
                line = f'{status}: {target} ({path})'
            elif target:
                line = f'{status}: {target}'
            else:
                line = status
            extra_lines.append(ActivityLine(line, style=NAVY_TEXT_MUTED, indent=1))
        if len(results) > 8:
            extra_lines.append(
                ActivityLine(
                    f'... {len(results) - 8} more symbols',
                    style=NAVY_TEXT_DIM,
                    indent=1,
                )
            )
        return extra_lines

    def read_symbols_results(
        scope: str,
        results: list[dict[str, object]],
        *,
        target_count: int | None = None,
        meta_lines: list[str] | None = None,
    ) -> ActivityCard:
        """Create an activity card for ``read_symbols`` tool results."""
        badge_category, title, verb = _SEARCH_CARD_PRESETS['read_symbols']
        count = len(results) if results else (target_count or 0)
        detail = f'{count} symbol{"s" if count != 1 else ""}'
        if scope:
            detail = f'{detail} in {scope}'
        extra_lines = ActivityRenderer._build_read_symbols_extra_lines(results)
        secondary = (
            ActivityRenderer._build_read_symbols_secondary(results)
            if results
            else None
        )
        return ActivityCard(
            verb=verb,
            detail=detail,
            badge_category=badge_category,
            title=title,
            secondary=secondary,
            secondary_kind='ok' if results else 'neutral',
            extra_lines=extra_lines,
            meta_lines=list(meta_lines or []),
            is_collapsible=bool(extra_lines),
        )

    @staticmethod
    def _build_analyze_structure_extra_lines(content: str) -> list[ActivityLine]:
        if not content:
            return []
        lines = content.splitlines()
        extra_lines: list[ActivityLine] = []
        for line in lines[:12]:
            extra_lines.append(
                ActivityLine(
                    line[:120] + ('…' if len(line) > 120 else ''),
                    style=NAVY_TEXT_MUTED,
                    indent=1,
                )
            )
        if len(lines) > 12:
            extra_lines.append(
                ActivityLine(
                    f'... {len(lines) - 12} more lines',
                    style=NAVY_TEXT_DIM,
                    indent=1,
                )
            )
        return extra_lines

    @staticmethod
    def analyze_structure_results(
        command: str,
        path: str,
        content: str,
        *,
        meta_lines: list[str] | None = None,
        error: str = '',
    ) -> ActivityCard:
        """Create an activity card for ``analyze_project_structure`` results."""
        badge_category, title, verb = _SEARCH_CARD_PRESETS['analyze']
        detail = f'{command} · {path}'.strip(' ·')
        extra_lines = ActivityRenderer._build_analyze_structure_extra_lines(content)
        if error:
            secondary = 'failed'
            secondary_kind = 'err'
        elif content:
            secondary = 'completed'
            secondary_kind = 'ok'
        else:
            secondary = 'no output'
            secondary_kind = 'neutral'
        return ActivityCard(
            verb=verb,
            detail=detail or 'project structure',
            badge_category=badge_category,
            title=title,
            secondary=secondary,
            secondary_kind=secondary_kind,
            extra_lines=extra_lines,
            meta_lines=list(meta_lines or []),
            is_collapsible=bool(extra_lines),
        )
