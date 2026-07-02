"""SQLite-backed disposable symbol index store."""

from __future__ import annotations

import logging
import shutil
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.context.symbol_index.builder import (
    IndexedFile,
    build_indexed_file,
    is_source_index_candidate,
    normalize_workspace_path,
)
from backend.context.symbol_index.paths import symbol_index_db_path, symbol_index_dir
from backend.engine.tools._file_ops import _SKIP_SYMBOL_SEARCH_PARTS

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    mtime_ns INTEGER NOT NULL,
    language TEXT NOT NULL,
    indexed_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    qualified_name TEXT NOT NULL,
    kind TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    signature_preview TEXT NOT NULL,
    FOREIGN KEY(path) REFERENCES files(path) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS imports (
    src_path TEXT NOT NULL,
    dst_path TEXT NOT NULL,
    PRIMARY KEY (src_path, dst_path),
    FOREIGN KEY(src_path) REFERENCES files(path) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_path ON symbols(path);
CREATE INDEX IF NOT EXISTS idx_symbols_qualified ON symbols(qualified_name);
"""


@dataclass(frozen=True)
class StoredSymbol:
    path: str
    name: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int
    signature_preview: str


class SymbolIndexStore:
    """Workspace-scoped symbol index with lazy per-file updates."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self.index_dirty = True
        self._cached_map: str | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        db_path = symbol_index_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        conn.executescript(_SCHEMA)
        conn.commit()
        self._conn = conn
        return conn

    def reset(self) -> None:
        """Delete the on-disk index and reopen an empty store."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
            shutil.rmtree(symbol_index_dir(), ignore_errors=True)
            self.index_dirty = True
            self._cached_map = None

    def _handle_error(self, exc: Exception) -> None:
        logger.warning('Symbol index error; resetting store: %s', exc)
        self.reset()

    def mark_dirty(self) -> None:
        with self._lock:
            self.index_dirty = True
            self._cached_map = None

    def invalidate_path(self, path: str) -> None:
        rel = normalize_workspace_path(path)
        if not rel:
            return
        with self._lock:
            try:
                conn = self._connect()
                conn.execute('DELETE FROM files WHERE path = ?', (rel,))
                conn.commit()
            except Exception as exc:
                self._handle_error(exc)
                return
            self.mark_dirty()

    def _file_is_fresh(self, path: Path, row: sqlite3.Row | None) -> bool:
        if row is None:
            return False
        try:
            stat = path.stat()
        except OSError:
            return False
        if int(row['mtime_ns']) != stat.st_mtime_ns:
            return False
        try:
            content = path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            return False
        from backend.engine.tools._file_ops import _sha256_text

        return row['content_hash'] == _sha256_text(content)

    def _upsert_indexed_file(self, indexed: IndexedFile) -> None:
        conn = self._connect()
        conn.execute('DELETE FROM files WHERE path = ?', (indexed.path,))
        conn.execute(
            """
            INSERT INTO files(path, content_hash, mtime_ns, language, indexed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                indexed.path,
                indexed.content_hash,
                indexed.mtime_ns,
                indexed.language,
                time.time(),
            ),
        )
        for symbol in indexed.symbols:
            conn.execute(
                """
                INSERT INTO symbols(
                    path, name, qualified_name, kind, start_line, end_line, signature_preview
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    indexed.path,
                    str(symbol.get('name') or ''),
                    str(symbol.get('qualified_name') or symbol.get('name') or ''),
                    str(symbol.get('symbol_kind') or symbol.get('kind') or ''),
                    int(symbol.get('start_line') or 0),
                    int(symbol.get('end_line') or 0),
                    str(symbol.get('signature') or symbol.get('preview') or '')[:240],
                ),
            )
        for dst in indexed.import_targets:
            conn.execute(
                'INSERT OR IGNORE INTO imports(src_path, dst_path) VALUES (?, ?)',
                (indexed.path, dst),
            )
        conn.commit()

    def ensure_indexed(self, rel_path: str) -> bool:
        rel = normalize_workspace_path(rel_path)
        if not rel or any(part in _SKIP_SYMBOL_SEARCH_PARTS for part in Path(rel).parts):
            return False
        abs_path = (self.workspace_root / rel).resolve()
        try:
            abs_path.relative_to(self.workspace_root)
        except ValueError:
            return False
        if not is_source_index_candidate(abs_path):
            return False

        with self._lock:
            try:
                conn = self._connect()
                row = conn.execute(
                    'SELECT path, content_hash, mtime_ns FROM files WHERE path = ?',
                    (rel,),
                ).fetchone()
                if self._file_is_fresh(abs_path, row):
                    return True
                indexed = build_indexed_file(abs_path, self.workspace_root)
                if indexed is None:
                    return False
                self._upsert_indexed_file(indexed)
                self.mark_dirty()
                return True
            except Exception as exc:
                self._handle_error(exc)
                return False

    def warm_paths(self, paths: list[str], *, limit: int = 500) -> int:
        indexed = 0
        for rel in paths:
            if indexed >= limit:
                break
            if self.ensure_indexed(rel):
                indexed += 1
        return indexed

    def list_indexed_paths(self) -> list[str]:
        with self._lock:
            try:
                conn = self._connect()
                rows = conn.execute('SELECT path FROM files ORDER BY path').fetchall()
                return [str(row['path']) for row in rows]
            except Exception as exc:
                self._handle_error(exc)
                return []

    def list_import_edges(self) -> list[tuple[str, str]]:
        with self._lock:
            try:
                conn = self._connect()
                rows = conn.execute(
                    'SELECT src_path, dst_path FROM imports'
                ).fetchall()
                return [(str(row['src_path']), str(row['dst_path'])) for row in rows]
            except Exception as exc:
                self._handle_error(exc)
                return []

    def symbols_for_file(self, rel_path: str) -> list[StoredSymbol]:
        rel = normalize_workspace_path(rel_path)
        with self._lock:
            try:
                conn = self._connect()
                rows = conn.execute(
                    """
                    SELECT path, name, qualified_name, kind, start_line, end_line, signature_preview
                    FROM symbols WHERE path = ? ORDER BY start_line
                    """,
                    (rel,),
                ).fetchall()
                return [
                    StoredSymbol(
                        path=str(row['path']),
                        name=str(row['name']),
                        qualified_name=str(row['qualified_name']),
                        kind=str(row['kind']),
                        start_line=int(row['start_line']),
                        end_line=int(row['end_line']),
                        signature_preview=str(row['signature_preview']),
                    )
                    for row in rows
                ]
            except Exception as exc:
                self._handle_error(exc)
                return []

    def search_symbols(
        self,
        query: str,
        *,
        path_prefix: str | None = None,
        symbol_kind: str | None = None,
        include_private: bool = False,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        q = query.strip().lower()
        if not q:
            return []
        clauses = ['(LOWER(name) LIKE ? OR LOWER(qualified_name) LIKE ?)']
        params: list[Any] = [f'%{q}%', f'%{q}%']
        if path_prefix:
            clauses.append('path LIKE ?')
            params.append(f'{normalize_workspace_path(path_prefix)}%')
        if symbol_kind:
            clauses.append('kind = ?')
            params.append(symbol_kind.strip().lower())
        if not include_private:
            clauses.append("substr(name, 1, 1) != '_'")
        sql = (
            'SELECT path, name, qualified_name, kind, start_line, end_line, signature_preview '
            f'FROM symbols WHERE {" AND ".join(clauses)} ORDER BY path, start_line LIMIT ?'
        )
        params.append(limit)
        with self._lock:
            try:
                conn = self._connect()
                rows = conn.execute(sql, params).fetchall()
                return [
                    {
                        'symbol_id': (
                            f'{row["path"]}:{row["start_line"]}-{row["end_line"]}:{row["name"]}'
                        ),
                        'name': row['name'],
                        'qualified_name': row['qualified_name'],
                        'kind': row['kind'],
                        'symbol_kind': row['kind'],
                        'path': row['path'],
                        'start_line': row['start_line'],
                        'end_line': row['end_line'],
                        'signature': row['signature_preview'],
                        'preview': row['signature_preview'],
                    }
                    for row in rows
                ]
            except Exception as exc:
                self._handle_error(exc)
                return []

    def is_warm(self) -> bool:
        return bool(self.list_indexed_paths())

    def get_cached_map(self) -> str | None:
        return self._cached_map

    def set_cached_map(self, content: str) -> None:
        self._cached_map = content
        self.index_dirty = False


_store_registry: dict[str, SymbolIndexStore] = {}
_registry_lock = threading.Lock()


def get_symbol_index_store(workspace_root: Path | str | None = None) -> SymbolIndexStore | None:
    try:
        if workspace_root is None:
            from backend.core.workspace_resolution import require_effective_workspace_root

            workspace_root = require_effective_workspace_root()
        root = Path(workspace_root).resolve()
    except Exception:
        return None
    key = str(root)
    with _registry_lock:
        store = _store_registry.get(key)
        if store is None:
            store = SymbolIndexStore(root)
            _store_registry[key] = store
        return store


def symbol_index_enabled(config: Any | None = None) -> bool:
    mode = 'lazy'
    if config is not None:
        mode = str(getattr(config, 'symbol_index_mode', 'lazy') or 'lazy').strip().lower()
    return mode != 'off'


def repo_map_enabled(config: Any | None = None) -> bool:
    if config is not None and getattr(config, 'enable_repo_map', True) is False:
        return False
    return symbol_index_enabled(config)
