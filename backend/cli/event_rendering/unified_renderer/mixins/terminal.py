"""Activity card builders — terminal domain."""

from __future__ import annotations

from backend.cli.event_rendering.unified_renderer.types import (
    ActivityCard,
    ActivityLine,
)
from backend.cli.event_rendering.unified_renderer.utils import (
    _looks_error_heavy,
    _strip_ansi,
)
from backend.cli.theme import NAVY_TEXT_DIM, NAVY_TEXT_MUTED


class _TerminalMixin:
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
        extra_lines.extend(_TerminalMixin._build_terminal_content_lines(content))
        secondary, kind = _TerminalMixin._build_terminal_secondary(
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
    def debugger_action(
        verb: str,
        detail: str,
        secondary: str | None = None,
        secondary_kind: str = 'neutral',
        extra_content: str | None = None,
    ) -> ActivityCard:
        """Create an activity card for a DAP debugger action/result."""
        extra_lines: list[ActivityLine] = []
        extra_lines.extend(_TerminalMixin._build_terminal_content_lines(extra_content))

        return ActivityCard(
            verb=verb,
            detail=detail,
            badge_category='debugger',
            title='Debugger',
            secondary=secondary,
            secondary_kind=secondary_kind,
            extra_lines=extra_lines,
            is_collapsible=True,
            start_collapsed=True,
            syntax_language='console',
        )
