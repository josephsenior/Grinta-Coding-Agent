"""Activity card builders — delegate domain."""

from __future__ import annotations

from backend.cli.event_rendering.unified_renderer.types import ActivityCard, ActivityLine
from backend.cli.event_rendering.unified_renderer.utils import _looks_error_heavy
from backend.cli.theme import NAVY_TEXT_DIM, NAVY_TEXT_MUTED


class _DelegateMixin:
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
