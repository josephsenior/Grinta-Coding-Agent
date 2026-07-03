"""Tests for the persistent symbol index and ranked repo map."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.context.symbol_index.builder import build_indexed_file
from backend.context.symbol_index.rank import rank_files_for_map
from backend.context.symbol_index.repo_map import build_repo_map_block, render_repo_map
from backend.context.symbol_index.store import (
    SymbolIndexStore,
    clear_symbol_index_for_workspace,
    get_symbol_index_store,
)
from backend.context.symbol_index import paths as index_paths


@pytest.fixture
def workspace_with_py(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / 'repo'
    root.mkdir()
    (root / 'app').mkdir()
    main = root / 'app' / 'main.py'
    main.write_text(
        'from app.util import helper\n\n'
        'def run():\n'
        '    return helper()\n',
        encoding='utf-8',
    )
    util = root / 'app' / 'util.py'
    util.write_text(
        'def helper():\n'
        '    return 1\n',
        encoding='utf-8',
    )
    index_dir = tmp_path / 'grinta_storage' / 'symbol_index'
    monkeypatch.setattr(index_paths, 'symbol_index_dir', lambda: index_dir)
    monkeypatch.setattr(
        index_paths,
        'symbol_index_db_path',
        lambda: index_dir / 'symbols.sqlite',
    )
    monkeypatch.setattr(
        'backend.context.symbol_index.store.symbol_index_dir',
        lambda: index_dir,
    )
    monkeypatch.setattr(
        'backend.context.symbol_index.store.symbol_index_db_path',
        lambda: index_dir / 'symbols.sqlite',
    )
    monkeypatch.setattr(
        'backend.core.workspace_resolution.require_effective_workspace_root',
        lambda: str(root),
    )
    monkeypatch.setattr(
        'backend.engine.tools._file_ops._workspace_root',
        lambda: root.resolve(),
    )
    monkeypatch.setattr(
        'backend.engine.tools._file_ops._relative_display_path',
        lambda path: str(path.resolve().relative_to(root.resolve())).replace('\\', '/'),
    )
    import backend.context.symbol_index.store as store_module

    store_module._store_registry.clear()
    return root


def test_index_file_stores_symbols_and_imports(workspace_with_py: Path) -> None:
    store = SymbolIndexStore(workspace_with_py)
    assert store.ensure_indexed('app/main.py') is True
    symbols = store.symbols_for_file('app/main.py')
    names = {symbol.name for symbol in symbols}
    assert 'run' in names
    edges = store.list_import_edges()
    assert ('app/main.py', 'app/util.py') in edges


def test_invalidate_path_marks_dirty(workspace_with_py: Path) -> None:
    store = SymbolIndexStore(workspace_with_py)
    store.ensure_indexed('app/main.py')
    store.set_cached_map('<REPO_MAP>cached</REPO_MAP>')
    store.invalidate_path('app/main.py')
    assert store.index_dirty is True
    assert store.get_cached_map() is None
    assert store.symbols_for_file('app/main.py') == []


def test_search_symbols_via_index(workspace_with_py: Path) -> None:
    store = SymbolIndexStore(workspace_with_py)
    store.ensure_indexed('app/main.py')
    store.ensure_indexed('app/util.py')
    hits = store.search_symbols('helper')
    assert any(hit['name'] == 'helper' for hit in hits)


def test_rank_prefers_imported_util(workspace_with_py: Path) -> None:
    store = SymbolIndexStore(workspace_with_py)
    ranked = rank_files_for_map(store, task='update helper', limit=10)
    assert 'app/util.py' in [path.replace('\\', '/') for path in ranked]
    assert 'app/main.py' in ranked


def test_render_repo_map_respects_markers(workspace_with_py: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = SymbolIndexStore(workspace_with_py)
    store.ensure_indexed('app/main.py')
    store.ensure_indexed('app/util.py')
    monkeypatch.setattr(
        'backend.context.symbol_index.repo_map.get_token_count',
        lambda text, model=None: len(text) // 4,
    )
    rendered = render_repo_map(store, task='fix helper', map_tokens=500)
    assert '<REPO_MAP>' in rendered
    assert '</REPO_MAP>' in rendered
    assert 'app/util.py' in rendered.replace('\\', '/')


def test_build_repo_map_block_skips_read_only(workspace_with_py: Path) -> None:
    class _Config:
        enable_repo_map = True
        map_tokens = 800
        symbol_index_mode = 'lazy'
        llm_config = None

    block = build_repo_map_block(
        task='what is this repo about?',
        config=_Config(),
        mode='agent',
    )
    assert block == ''


def test_reset_on_corrupt_query(workspace_with_py: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = SymbolIndexStore(workspace_with_py)
    store.ensure_indexed('app/main.py')
    db_path = index_paths.symbol_index_db_path()

    def boom(*_args, **_kwargs):
        raise RuntimeError('db broken')

    monkeypatch.setattr(store, '_connect', boom)
    store.search_symbols('run')
    assert not db_path.exists() or store._conn is None


def test_get_symbol_index_store_singleton(workspace_with_py: Path) -> None:
    store_a = get_symbol_index_store(workspace_with_py)
    store_b = get_symbol_index_store(workspace_with_py)
    assert store_a is store_b


def test_clear_symbol_index_for_workspace_wipes_cache_and_db(
    workspace_with_py: Path,
) -> None:
    store = SymbolIndexStore(workspace_with_py)
    store.ensure_indexed('app/main.py')
    store.set_cached_map('<REPO_MAP>stale</REPO_MAP>')
    import backend.context.symbol_index.store as store_module

    store_module._store_registry[str(workspace_with_py.resolve())] = store
    clear_symbol_index_for_workspace(workspace_with_py)
    assert store.get_cached_map() is None
    assert store.index_dirty is True
    assert store.symbols_for_file('app/main.py') == []
