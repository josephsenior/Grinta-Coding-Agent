"""Per-server LSP timeout profiles."""

from __future__ import annotations

# JVM / project-index servers need longer cold-start and query budgets.
SLOW_LSP_SERVERS: frozenset[str] = frozenset(
    {
        'jdtls',
        'metals',
        'kotlin-language-server',
        'haskell-language-server',
        'elixir-ls',
        'csharp-ls',
        'omnisharp',
        'fsautocomplete',
        'julials',
        'dart',
    }
)

_DEFAULT_QUERY_TIMEOUT_SEC = 15.0
_SLOW_QUERY_TIMEOUT_SEC = 45.0
_DEFAULT_INIT_TIMEOUT_SEC = 20.0
_SLOW_INIT_TIMEOUT_SEC = 60.0
_POST_EDIT_SLOW_FLOOR_SEC = 12.0


def init_timeout_for_server(server_name: str) -> float:
    if server_name in SLOW_LSP_SERVERS:
        return _SLOW_INIT_TIMEOUT_SEC
    return _DEFAULT_INIT_TIMEOUT_SEC


def query_timeout_for_server(server_name: str) -> float:
    if server_name in SLOW_LSP_SERVERS:
        return _SLOW_QUERY_TIMEOUT_SEC
    return _DEFAULT_QUERY_TIMEOUT_SEC


def effective_query_timeout(
    server_name: str, requested: float | None, *, post_edit: bool = False
) -> float:
    """Resolve the query timeout, honoring slow-server floors when needed."""
    profile = query_timeout_for_server(server_name)
    if requested is None:
        return profile
    if post_edit and server_name in SLOW_LSP_SERVERS:
        return max(requested, min(profile, _POST_EDIT_SLOW_FLOOR_SEC))
    return requested
