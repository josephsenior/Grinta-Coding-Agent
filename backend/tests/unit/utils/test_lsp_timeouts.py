"""Unit tests for LSP timeouts profiling."""

from __future__ import annotations

from backend.utils.lsp.lsp_timeouts import (
    effective_query_timeout,
    init_timeout_for_server,
    query_timeout_for_server,
)


def test_init_timeout_for_server() -> None:
    # Slow server
    assert init_timeout_for_server('jdtls') == 60.0
    # Default server
    assert init_timeout_for_server('pyright') == 20.0


def test_query_timeout_for_server() -> None:
    # Slow server
    assert query_timeout_for_server('metals') == 45.0
    # Default server
    assert query_timeout_for_server('ruff') == 15.0


def test_effective_query_timeout() -> None:
    # 1. requested is None -> returns default profile
    assert effective_query_timeout('metals', None) == 45.0
    assert effective_query_timeout('pyright', None) == 15.0

    # 2. requested is not None, post_edit is False -> returns requested
    assert effective_query_timeout('pyright', 8.0, post_edit=False) == 8.0

    # 3. requested is not None, post_edit is True
    # Slow server: floor is 12s, max(requested, min(profile, floor)) -> max(requested, 12)
    assert effective_query_timeout('metals', 3.0, post_edit=True) == 12.0
    assert effective_query_timeout('metals', 20.0, post_edit=True) == 20.0

    # Default server: floor is 5s, max(requested, min(profile, floor)) -> max(requested, 5)
    assert effective_query_timeout('pyright', 3.0, post_edit=True) == 5.0
    assert effective_query_timeout('pyright', 8.0, post_edit=True) == 8.0
