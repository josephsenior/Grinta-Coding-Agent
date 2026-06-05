"""Vector storage backends and the enhanced (hybrid + LRU-cached) vector store.

Public API re-exports — implementation is split across:

- :mod:`backend.context.vector_store._local_vector_store`: ``VectorBackend``
  ABC, ``ChromaDBBackend`` (ChromaDB / ONNX MiniLM), ``SQLiteBM25Backend``
  (SQLite FTS5), and the ``_default_memory_persist_directory`` helper.
- :mod:`backend.context.vector_store._vector_store`: ``QueryCache`` (LRU +
  TTL) and ``EnhancedVectorStore`` (hybrid semantic + BM25 search that
  combines both backends).

Requires the optional ``[rag]`` extra (``pip install 'grinta-ai[rag]'``).
"""

from __future__ import annotations

from backend.context.vector_store._local_vector_store import (
    ChromaDBBackend,
    SQLiteBM25Backend,
    VectorBackend,
    _default_memory_persist_directory,
)
from backend.context.vector_store._vector_store import (
    EnhancedVectorStore,
    QueryCache,
)

__all__ = [
    'ChromaDBBackend',
    'EnhancedVectorStore',
    'QueryCache',
    'SQLiteBM25Backend',
    'VectorBackend',
    '_default_memory_persist_directory',
]
