"""Query helpers for the symbol index."""

from __future__ import annotations

from typing import Any

from backend.context.symbol_index.store import (
    get_symbol_index_store,
    symbol_index_enabled,
)


def find_symbols_via_index(
    query: str,
    *,
    path: str | None = None,
    symbol_kind: str | None = None,
    include_private: bool = False,
    config: Any | None = None,
) -> list[dict[str, Any]] | None:
    if not symbol_index_enabled(config):
        return None
    store = get_symbol_index_store()
    if store is None:
        return None
    if path:
        store.ensure_indexed(path)
    elif not store.is_warm():
        return None
    results = store.search_symbols(
        query,
        path_prefix=path,
        symbol_kind=symbol_kind,
        include_private=include_private,
    )
    return results
