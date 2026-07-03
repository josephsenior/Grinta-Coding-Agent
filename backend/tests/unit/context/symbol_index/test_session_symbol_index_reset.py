"""Session start clears stale symbol index / repo map."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.context.memory.session_context import bind_session_context
from backend.context.symbol_index.store import SymbolIndexStore, get_symbol_index_store
import backend.context.memory.session_context as session_context_module
import backend.context.symbol_index.store as store_module


@pytest.fixture
def workspace_with_py(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / 'repo'
    root.mkdir()
    (root / 'app').mkdir()
    (root / 'app' / 'main.py').write_text('def run():\n    return 1\n', encoding='utf-8')
    monkeypatch.setattr(
        'backend.core.workspace_resolution.require_effective_workspace_root',
        lambda: str(root),
    )
    store_module._store_registry.clear()
    session_context_module._last_session_symbol_index_cleared = None
    return root


def test_bind_session_context_clears_symbol_index_once_per_session(
    workspace_with_py: Path,
) -> None:
    store = get_symbol_index_store(workspace_with_py)
    assert store is not None
    store.ensure_indexed('app/main.py')
    store.set_cached_map('<REPO_MAP>stale</REPO_MAP>')

    bind_session_context(session_id='session-a')
    assert store.get_cached_map() is None
    assert store.index_dirty is True

    store.set_cached_map('<REPO_MAP>rebuilt</REPO_MAP>')
    bind_session_context(session_id='session-a')
    assert store.get_cached_map() == '<REPO_MAP>rebuilt</REPO_MAP>'

    bind_session_context(session_id='session-b')
    assert store.get_cached_map() is None
