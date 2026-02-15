"""Local vector store implementation using ChromaDB."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class VectorBackend(ABC):
    """Abstract base class for vector storage backends."""

    @abstractmethod
    def add(
        self,
        step_id: str,
        role: str,
        artifact_hash: str | None,
        rationale: str | None,
        content_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add a document to the vector store."""

    @abstractmethod
    def search(
        self, query: str, k: int = 5, filter_metadata: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Search for similar documents."""

    @abstractmethod
    def delete_by_metadata(self, filter_metadata: dict[str, Any]) -> int:
        """Delete documents matching metadata filters."""

    @abstractmethod
    def delete_by_ids(self, ids: list[str]) -> int:
        """Delete documents by their IDs."""

    @abstractmethod
    def stats(self) -> dict[str, Any]:
        """Get statistics about the vector store."""


class ChromaDBBackend(VectorBackend):
    """Local ChromaDB backend for vector storage."""

    def __init__(
        self,
        collection_name: str = "FORGE_memory",
        persist_directory: Path | None = None,
    ) -> None:
        r"""Initialize ChromaDB local vector store.

        Args:
            collection_name: Name of ChromaDB collection
            persist_directory: Directory for persistent storage

        """
        try:
            import chromadb
            from chromadb.config import Settings
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            msg = f"ChromaDB backend requires: pip install chromadb sentence-transformers\nOriginal error: {e}"
            raise ImportError(msg) from e

        if persist_directory is None:
            persist_directory = Path.home() / ".Forge" / "memory" / "chroma"
        persist_directory.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(
            path=str(persist_directory),
            settings=Settings(anonymized_telemetry=False),
        )

        # Use lightweight model for local development
        model_name = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        logger.info("Loading local embedding model: %s", model_name)
        self.model = SentenceTransformer(model_name)

        try:
            self.collection = self.client.get_collection(name=collection_name)
            logger.info(
                "Loaded ChromaDB collection with %s documents", self.collection.count()
            )
        except Exception:
            self.collection = self.client.create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("Created new ChromaDB collection")

    def add(
        self,
        step_id: str,
        role: str,
        artifact_hash: str | None,
        rationale: str | None,
        content_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Insert a new document embedding into the local ChromaDB collection."""
        text = self._prepare_text(rationale, content_text)
        embedding = self.model.encode(text, show_progress_bar=False).tolist()

        doc_metadata = {
            "step_id": step_id,
            "role": role,
            "timestamp": time.time(),
            **(metadata or {}),
        }
        if artifact_hash:
            doc_metadata["artifact_hash"] = artifact_hash

        self.collection.add(
            ids=[step_id],
            embeddings=[embedding],  # type: ignore[arg-type]
            documents=[text[:2000]],
            metadatas=[doc_metadata],
        )

    def search(
        self, query: str, k: int = 5, filter_metadata: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Search the collection for the most similar documents to the query."""
        if self.collection.count() == 0:
            return []

        query_embedding = self.model.encode(query, show_progress_bar=False).tolist()
        results = self.collection.query(
            query_embeddings=[query_embedding],  # type: ignore[arg-type]
            n_results=min(k, self.collection.count()),
            where=filter_metadata,
            include=["documents", "metadatas", "distances"],
        )

        if (
            not results["ids"]
            or not results["documents"]
            or not results["metadatas"]
            or not results["distances"]
        ):
            return []

        return [
            {
                "step_id": results["ids"][0][i],
                "score": 1.0 - results["distances"][0][i],
                "excerpt": results["documents"][0][i],
                **results["metadatas"][0][i],
            }
            for i in range(len(results["ids"][0]))
        ]

    async def async_add(
        self,
        step_id: str,
        role: str,
        artifact_hash: str | None,
        rationale: str | None,
        content_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Non-blocking add using a thread to encode and persist."""
        await asyncio.to_thread(
            self.add, step_id, role, artifact_hash, rationale, content_text, metadata
        )

    async def async_search(
        self,
        query: str,
        k: int = 5,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Non-blocking search wrapper."""
        return await asyncio.to_thread(self.search, query, k, filter_metadata)

    def delete_by_metadata(self, filter_metadata: dict[str, Any]) -> int:
        """Delete documents matching metadata filters."""
        try:
            self.collection.delete(where=filter_metadata)
            logger.info("Deleted documents from ChromaDB matching %s", filter_metadata)
            return 1
        except Exception as e:
            logger.error("Failed to delete from ChromaDB: %s", e)
            return 0

    def delete_by_ids(self, ids: list[str]) -> int:
        """Delete documents by their IDs."""
        try:
            self.collection.delete(ids=ids)
            logger.info("Deleted %s documents from ChromaDB", len(ids))
            return len(ids)
        except Exception as e:
            logger.error("Failed to delete from ChromaDB: %s", e)
            return 0

    def stats(self) -> dict[str, Any]:
        """Return metadata about the local ChromaDB collection."""
        return {
            "backend": "ChromaDB (Local)",
            "num_documents": self.collection.count(),
            "embedding_dim": self.model.get_sentence_embedding_dimension(),
        }

    @staticmethod
    def _prepare_text(rationale: str | None, content: str) -> str:
        """Prepare combined text for embedding."""
        parts = []
        if rationale:
            parts.append(rationale)
        if content:
            parts.append(content[:2000])
        return "\n".join(parts)


__all__ = ["ChromaDBBackend"]
