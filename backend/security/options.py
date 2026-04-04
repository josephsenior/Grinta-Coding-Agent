"""Security analyzer options and registry."""

from __future__ import annotations

from typing import Any

from backend.security.analyzer import SecurityAnalyzer

# Registry of available security analyzers
# Maps analyzer name to analyzer class
SecurityAnalyzers: dict[str, type[SecurityAnalyzer]] = {
    'default': SecurityAnalyzer,
}


def get_security_analyzer(
    name: str = 'default',
    config: dict[str, Any] | None = None,
) -> SecurityAnalyzer:
    """Instantiate a registered security analyzer.

    Args:
        name: Analyzer key in the registry (default: ``"default"``).
        config: Optional configuration dict forwarded to the analyzer.

    Returns:
        A :class:`SecurityAnalyzer` instance.

    Raises:
        KeyError: If *name* is not in the registry.
    """
    cls = SecurityAnalyzers[name]
    return cls(config=config)


__all__ = ['SecurityAnalyzers', 'get_security_analyzer']
