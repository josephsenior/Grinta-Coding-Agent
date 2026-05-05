"""Rate limiting and quota error guidance rules."""

from __future__ import annotations

from backend.cli._event_renderer.error_categories._matchers import _any
from backend.cli._event_renderer.panels import ErrorGuidance, _GuidanceRule

RATE_LIMIT_GUIDANCE_RULES: tuple[_GuidanceRule, ...] = (
    _GuidanceRule(
        _any(
            'provider limit reached',
            'ratelimiterror:',
            'serviceunavailableerror:',
        ),
        ErrorGuidance(
            summary='The provider is briefly limiting requests (rate or capacity).',
            steps=(
                'Grinta retries automatically when this happens — no action needed for a single pause.',
                'If it keeps repeating, wait a minute, try another model in /settings, or check quota/billing on the provider dashboard.',
            ),
            error_code='ERR-RATE-001',
        ),
    ),
    _GuidanceRule(
        _any(
            '429',
            'rate limit',
            'too many requests',
            'insufficient_quota',
            'quota',
            'billing',
        ),
        ErrorGuidance(
            summary='The provider is rejecting more requests because of rate or billing limits.',
            steps=(
                'Wait a moment and retry.',
                'Switch to another model in /settings if you need to keep working right now.',
                'Check the provider dashboard for quota, spend, or billing problems.',
            ),
            error_code='ERR-RATE-002',
        ),
    ),
)

__all__ = ['RATE_LIMIT_GUIDANCE_RULES']
