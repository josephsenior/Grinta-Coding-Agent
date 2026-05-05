"""Shared matcher functions for error guidance rules."""

from __future__ import annotations


def _all(*needles: str):
    """Match when ALL needles are present in the lowercased error text."""
    return lambda lower: all(n in lower for n in needles)


def _any(*needles: str):
    """Match when ANY needle is present in the lowercased error text."""
    return lambda lower: any(n in lower for n in needles)


def _has(needle: str):
    """Match when the specific needle is present."""
    return lambda lower: needle in lower


def _and(*preds):
    """Combine multiple predicates with AND logic."""
    return lambda lower: all(p(lower) for p in preds)


def _no_api_key_match(lower: str) -> bool:
    """Match API key / authentication failures."""
    if 'no api key or model configured' in lower:
        return True
    return 'initialization failed' in lower and any(
        n in lower
        for n in (
            'authenticationerror',
            'invalid api key',
            'api_key',
            'unauthorized',
            '401',
        )
    )


def _context_size_match(lower: str) -> bool:
    """Match context window / token limit errors."""
    return 'context' in lower and any(
        n in lower for n in ('length', 'window', 'limit', 'too many tokens')
    )


__all__ = ['_all', '_any', '_has', '_and', '_no_api_key_match', '_context_size_match']
