"""Authentication and authorization error guidance rules."""

from __future__ import annotations

from backend.cli.event_rendering.error_categories.matchers import (
    _any,
    _no_api_key_match,
)
from backend.cli.event_rendering.panels import ErrorGuidance, _GuidanceRule

AUTH_GUIDANCE_RULES: tuple[_GuidanceRule, ...] = (
    _GuidanceRule(
        _no_api_key_match,
        ErrorGuidance(
            summary='The engine could not finish startup with the current credentials.',
            steps=(
                'Restart grinta and complete onboarding so it can prompt for a model and API key.',
                'Or update settings.json with a valid provider, model, and API key before retrying.',
                'Rerun the same task after saving the new settings.',
            ),
            error_code='ERR-AUTH-001',
        ),
    ),
    _GuidanceRule(
        _any(
            '401',
            'unauthorized',
            'invalid api key',
            'authenticationerror',
            'api key rejected',
        ),
        ErrorGuidance(
            summary='The provider rejected the configured credentials.',
            steps=(
                'Open /settings, press k, and update the API key.',
                'Press m in /settings to confirm the selected model belongs to that provider.',
                'Send the request again after saving the updated settings.',
            ),
            error_code='ERR-AUTH-002',
        ),
    ),
    _GuidanceRule(
        _any('permission denied', 'access is denied', 'forbidden', '403'),
        ErrorGuidance(
            summary='The current account or filesystem permissions are blocking the action.',
            steps=(
                'Verify the API key has access to the selected model or endpoint.',
                'If this is a local file action, reopen grinta from a writable directory and retry.',
            ),
            error_code='ERR-AUTH-003',
        ),
    ),
)

__all__ = ['AUTH_GUIDANCE_RULES']
