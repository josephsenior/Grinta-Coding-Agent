"""Activity card builders — code domain."""

from __future__ import annotations

from backend.cli.event_rendering.unified_renderer.types import ActivityCard, ActivityLine
from backend.cli.theme import NAVY_TEXT_MUTED


class _CodeMixin:
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
