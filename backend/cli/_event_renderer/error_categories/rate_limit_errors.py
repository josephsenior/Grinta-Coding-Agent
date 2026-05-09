"""Rate limiting and quota error guidance rules."""

from __future__ import annotations

from backend.cli._event_renderer.error_categories._matchers import _any
from backend.cli._event_renderer.panels import ErrorGuidance, _GuidanceRule

# These strings come verbatim from provider SDKs and RecoveryService log lines.
# Keep them specific so generic words like "quota" or "billing" in file paths
# or user messages do not trigger a false-positive rate-limit notice.
RATE_LIMIT_GUIDANCE_RULES: tuple[_GuidanceRule, ...] = (
    _GuidanceRule(
        _any(
            # RecoveryService/litellm compact error class names
            'ratelimiterror',
            'serviceunavailableerror',
            # Grinta internal: RecoveryService emits this phrase
            'provider limit reached',
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
            # HTTP status phrases as returned by providers
            '429 too many requests',
            # Phrase-level matches only — avoids matching unrelated "rate" or "limit" words
            'rate limit exceeded',
            'rate limit reached',
            'rate limit hit',
            'rate_limit_exceeded',
            'too many requests',
            # OpenAI / Azure quota phrases
            'insufficient_quota',
            'quota exceeded',
            'quota has been exceeded',
            # Billing-specific phrases
            'billing hard limit',
            'billing limit reached',
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
