"""Persistent workspace symbol index and ranked repo map."""

from backend.context.symbol_index.paths import symbol_index_db_path, symbol_index_dir
from backend.context.symbol_index.repo_map import build_repo_map_block, render_repo_map
from backend.context.symbol_index.store import (
    SymbolIndexStore,
    get_symbol_index_store,
    repo_map_enabled,
    symbol_index_enabled,
)

__all__ = [
    'SymbolIndexStore',
    'build_repo_map_block',
    'get_symbol_index_store',
    'render_repo_map',
    'repo_map_enabled',
    'symbol_index_dir',
    'symbol_index_db_path',
    'symbol_index_enabled',
]
