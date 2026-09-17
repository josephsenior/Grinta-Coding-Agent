"""History search storage: pluggable backends and the LRU-cached search store.

Public API re-exports — implementation is split across:

- :mod:`backend.context.vector_store._local_vector_store`: the ``VectorBackend``
  interface, ``SQLiteBM25Backend`` (SQLite FTS5 keyword search, standard
  library only), and the ``_default_memory_persist_directory`` helper.
- :mod:`backend.context.vector_store._vector_store`: ``QueryCache`` (LRU +
  TTL) and ``EnhancedVectorStore`` (tenant-scoped search over one backend).

No optional dependencies: this backs ``search_history`` on every install.
"""

from __future__ import annotations

from backend.context.vector_store._local_vector_store import (
    SQLiteBM25Backend,
    VectorBackend,
    _default_memory_persist_directory,
)
from backend.context.vector_store._vector_store import (
    EnhancedVectorStore,
    QueryCache,
)

__all__ = [
    'EnhancedVectorStore',
    'QueryCache',
    'SQLiteBM25Backend',
    'VectorBackend',
    '_default_memory_persist_directory',
]
