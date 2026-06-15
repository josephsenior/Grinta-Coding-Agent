"""Browser tool error guidance rules."""

from __future__ import annotations

from backend.cli.event_rendering.error_categories.matchers import _any
from backend.cli.event_rendering.panels import ErrorGuidance, _GuidanceRule

BROWSER_GUIDANCE_RULES: tuple[_GuidanceRule, ...] = (
    _GuidanceRule(
        _any(
            'browser screenshot timed out',
            'browser screenshot failed',
            'browser snapshot timed out',
            'snapshot timed out',
            'screenshot timed out',
            'tried compositor and window capture',
            'navigation to ',
        ),
        ErrorGuidance(
            summary='The browser tool did not finish in time.',
            steps=(
                'A JavaScript alert/confirm/prompt dialog on the page may be '
                'blocking rendering; we now auto-dismiss these before '
                'screenshots, but it can still happen on other commands. '
                'Try ``browser snapshot`` to probe DOM state without rendering.',
                'Re-run ``browser navigate`` to the same URL to reset the tab, '
                'or close stray Chrome/Chromium windows and retry.',
                'Set GRINTA_BROWSER_TRACE=1 before launching to see stage '
                'timings on stderr.',
            ),
            error_code='ERR-BROWSER-001',
        ),
    ),
)

__all__ = ['BROWSER_GUIDANCE_RULES']
