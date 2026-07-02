"""Filesystem locations for the workspace symbol index."""

from __future__ import annotations

from pathlib import Path

from backend.persistence.locations import get_active_local_data_root


def symbol_index_dir() -> Path:
    """Return the disposable symbol-index directory for the active workspace."""
    return Path(get_active_local_data_root()) / 'symbol_index'


def symbol_index_db_path() -> Path:
    return symbol_index_dir() / 'symbols.sqlite'
