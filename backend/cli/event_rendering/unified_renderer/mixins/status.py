"""Activity card builders — status domain."""

from __future__ import annotations

from backend.cli.event_rendering.unified_renderer.types import (
    ActivityCard,
    ActivityLine,
)


class _StatusMixin:
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
