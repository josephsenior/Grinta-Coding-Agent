"""Network connection error guidance rules."""

from __future__ import annotations

from backend.cli.event_rendering.error_categories.matchers import _any
from backend.cli.event_rendering.panels import ErrorGuidance, _GuidanceRule

NETWORK_GUIDANCE_RULES: tuple[_GuidanceRule, ...] = (
    _GuidanceRule(
        _any(
            'econnrefused',
            'connection refused',
            'name or service not known',
            'nodename nor servname',
            'getaddrinfo failed',
        ),
        ErrorGuidance(
            summary='Grinta could not open a network connection to the host.',
            steps=(
                'Verify the base URL in /settings and that the service is running.',
                'Check VPN, proxy, and firewall rules; retry on a stable network.',
                'For local servers (Ollama, LM Studio), confirm the port is listening.',
            ),
            error_code='ERR-NET-001',
        ),
    ),
    _GuidanceRule(
        _any('connection', 'connect error', 'unreachable', 'dns', 'ssl', 'certificate'),
        ErrorGuidance(
            summary='Grinta could not reach the model provider.',
            steps=(
                'Check your internet connection, VPN, proxy, or firewall rules.',
                'Retry after the connection is stable.',
            ),
            error_code='ERR-NET-002',
        ),
    ),
)

__all__ = ['NETWORK_GUIDANCE_RULES']
