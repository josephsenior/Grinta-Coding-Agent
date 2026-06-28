"""Activity card builders — browser domain."""

from __future__ import annotations

from backend.cli.event_rendering.unified_renderer.types import (
    ActivityCard,
    ActivityLine,
)
from backend.cli.event_rendering.unified_renderer.utils import (
    _BROWSER_OUTCOMES,
    _exploration_meta_line,
)
from backend.cli.theme import NAVY_ERROR


class _BrowserMixin:
    @staticmethod
    def browser_action(
        action_name: str,
        url: str = '',
        result: str | None = None,
        error: str | None = None,
    ) -> ActivityCard:
        """Create an activity card for a browser action."""
        from backend.cli.tool_display.renderers.browser import (
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
        if error:
            extra_lines.append(
                ActivityLine(f'Error: {error}', style=NAVY_ERROR, indent=0)
            )

        meta_tokens: list[str] = []
        if url:
            meta_tokens.append(f'url: {url[:60]}')

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
