"""Error guidance rules organized by category.

This package splits the large ``_GUIDANCE_RULES`` tuple from ``error_panel.py``
into smaller, focused modules that are easier to maintain and extend.

Usage::

    from backend.cli._event_renderer.error_categories import (
        get_all_guidance_rules,
        get_notice_title_rules,
    )
"""

from __future__ import annotations

from backend.cli._event_renderer.error_categories.auth_errors import (
    AUTH_GUIDANCE_RULES,
)
from backend.cli._event_renderer.error_categories.browser_errors import (
    BROWSER_GUIDANCE_RULES,
)
from backend.cli._event_renderer.error_categories.model_errors import (
    MODEL_GUIDANCE_RULES,
)
from backend.cli._event_renderer.error_categories.network_errors import (
    NETWORK_GUIDANCE_RULES,
)
from backend.cli._event_renderer.error_categories.rate_limit_errors import (
    RATE_LIMIT_GUIDANCE_RULES,
)
from backend.cli._event_renderer.error_categories.system_errors import (
    SYSTEM_GUIDANCE_RULES,
)
from backend.cli._event_renderer.error_categories.timeout_errors import (
    TIMEOUT_GUIDANCE_RULES,
)

# Order matters: first match wins.  Keep specific rules before generic ones
# and group by category for readability.
# Browser rules must come before generic timeout rules to match
# browser-specific timeouts correctly.
ALL_GUIDANCE_RULES: tuple = (
    *AUTH_GUIDANCE_RULES,
    *NETWORK_GUIDANCE_RULES,
    *RATE_LIMIT_GUIDANCE_RULES,
    *BROWSER_GUIDANCE_RULES,
    *TIMEOUT_GUIDANCE_RULES,
    *MODEL_GUIDANCE_RULES,
    *SYSTEM_GUIDANCE_RULES,
)

# Notice title matchers (used by ``notice_panel_title``)
NOTICE_TITLE_RULES: tuple = (
    (lambda lower: 'verification required' in lower, 'Need fresh evidence'),
    (
        lambda lower: any(s in lower for s in ('no executable action', 'no-progress loop')),
        'Paused safely',
    ),
    (lambda lower: 'intermediate control tool' in lower, 'Continuing work'),
    (lambda lower: 'fallback completion timed out' in lower, 'Still no reply'),
    (
        lambda lower: any(
            s in lower
            for s in ('rate limit', 'provider limit', 'too many requests', '429', 'quota', 'billing')
        ),
        'Rate or quota limit',
    ),
    (
        lambda lower: any(
            s in lower for s in ('connection', 'unreachable', 'connect error', 'dns', 'ssl', 'certificate')
        ),
        'Connection issue',
    ),
    (lambda lower: 'debugger start failed during' in lower, 'Debugger startup issue'),
    (lambda lower: 'default shell session not initialized' in lower, 'Shell session issue'),
    (lambda lower: 'stuck loop' in lower, 'Stuck pattern'),
    (lambda lower: any(s in lower for s in ('timeout', 'timed out', 'did not answer')), 'Request timed out'),
)


def get_all_guidance_rules() -> tuple:
    """Return the complete ordered list of guidance rules."""
    return ALL_GUIDANCE_RULES


def get_notice_title_rules() -> tuple:
    """Return the notice title matching rules."""
    return NOTICE_TITLE_RULES


__all__ = [
    'ALL_GUIDANCE_RULES',
    'NOTICE_TITLE_RULES',
    'get_all_guidance_rules',
    'get_notice_title_rules',
]
