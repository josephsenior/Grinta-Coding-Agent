"""Activity card builders — file domain."""

from __future__ import annotations

from backend.cli.event_rendering.unified_renderer.types import (
    ActivityCard,
    ActivityLine,
)
from backend.cli.event_rendering.unified_renderer.utils import (
    _lexer_for_path,
    _looks_error_heavy,
)
from backend.cli.theme import NAVY_TEXT_DIM, NAVY_WAITING


class _FileMixin:
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
        secondary = _FileMixin._build_edit_secondary(added, removed)
        extra_lines = _FileMixin._build_diff_extra_lines(diff_lines)
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
