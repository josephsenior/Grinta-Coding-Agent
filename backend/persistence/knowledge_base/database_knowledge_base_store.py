"""Database-based knowledge base storage implementation using PostgreSQL.

Stores knowledge base collections and documents in PostgreSQL for production use.
Includes automatic schema initialization and strict resource management.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import asyncpg
from asyncpg import Pool

from backend.core.logger import forge_logger as logger
from backend.persistence.data_models.knowledge_base import (
    KnowledgeBaseCollection,
    KnowledgeBaseDocument,
)

if TYPE_CHECKING:
    pass

# SQL Schema for self-initialization
INIT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS knowledge_base_collections (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    document_count INTEGER DEFAULT 0,
    total_size_bytes BIGINT DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_base_documents (
    id TEXT PRIMARY KEY,
    collection_id TEXT REFERENCES knowledge_base_collections(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    file_size_bytes BIGINT DEFAULT 0,
    mime_type TEXT,
    content_preview TEXT,
    chunk_count INTEGER DEFAULT 0,
    uploaded_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_kb_col_user ON knowledge_base_collections(user_id);
CREATE INDEX IF NOT EXISTS idx_kb_doc_col ON knowledge_base_documents(collection_id);
CREATE INDEX IF NOT EXISTS idx_kb_doc_hash ON knowledge_base_documents(content_hash);
"""


# Global factory helper for lazy pool access
async def get_kb_db_pool() -> Pool:
    """Get the shared database pool from the application."""
    from backend.persistence.database_pool import get_db_pool

    return await get_db_pool()


class DatabaseKnowledgeBaseStore:
    """PostgreSQL-based implementation of knowledge base storage.

    Design Philosophy:
    - Dependency Injection: connection pool is passed in, not created ad-hoc.
    - Self-Healing: ensures tables exist on startup.
    - Atomic: uses explicit transactions for data integrity.
    """

    def __init__(self, pool: Pool | None = None):
        """Initialize database knowledge base store.

        Args:
            pool: An initialized asyncpg connection pool.
                  If None, will attempt to retrieve the global app pool lazily.
        """
        self._pool = pool

    async def _get_pool(self) -> Pool:
        """Get database connection pool, resolving lazily if needed."""
        if self._pool is None:
            self._pool = await get_kb_db_pool()
        return self._pool

    async def initialize(self) -> None:
        """Run startup creation of tables if they don't exist."""
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.execute(INIT_SCHEMA_SQL)
                logger.info("Knowledge Base database schema verified/initialized.")
        except Exception as e:
            logger.critical(
                "Failed to initialize Knowledge Base database schema: %s", e
            )
            raise

    async def create_collection(
        self, user_id: str, name: str, description: str | None = None
    ) -> KnowledgeBaseCollection:
        """Create a new collection."""
        collection = KnowledgeBaseCollection(
            user_id=user_id,
            name=name,
            description=description,
            document_count=0,
            total_size_bytes=0,
        )

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO knowledge_base_collections (
                        id, user_id, name, description, document_count,
                        total_size_bytes, created_at, updated_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    collection.id,
                    collection.user_id,
                    collection.name,
                    collection.description,
                    collection.document_count,
                    collection.total_size_bytes,
                    collection.created_at,
                    collection.updated_at,
                )

        logger.info("Created collection: %s (%s)", collection.name, collection.id)
        return collection

    async def get_collection(
        self, collection_id: str
    ) -> KnowledgeBaseCollection | None:
        """Get a collection by ID."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM knowledge_base_collections WHERE id = $1",
                collection_id,
            )
            return self._row_to_collection(row) if row else None

    async def list_collections(self, user_id: str) -> list[KnowledgeBaseCollection]:
        """List all collections for a user."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM knowledge_base_collections WHERE user_id = $1 ORDER BY created_at DESC",
                user_id,
            )
            return [self._row_to_collection(row) for row in rows]

    async def update_collection(
        self,
        collection_id: str,
        name: str | None = None,
        description: str | None = None,
    ) -> KnowledgeBaseCollection | None:
        """Update a collection."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                updates = []
                params: list[Any] = []
                param_idx = 1

                if name is not None:
                    updates.append(f"name = ${param_idx}")
                    params.append(name)
                    param_idx += 1

                if description is not None:
                    updates.append(f"description = ${param_idx}")
                    params.append(description)
                    param_idx += 1

                if not updates:
                    return await self.get_collection(collection_id)

                updates.append(f"updated_at = ${param_idx}")
                params.append(datetime.now(UTC))
                param_idx += 1

                params.append(collection_id)

                query = f"""
                    UPDATE knowledge_base_collections
                    SET {", ".join(updates)}
                    WHERE id = ${param_idx}
                    RETURNING *
                """

                row = await conn.fetchrow(query, *params)
                return self._row_to_collection(row) if row else None

    async def delete_collection(self, collection_id: str) -> bool:
        """Delete a collection and all its documents."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Note: ON DELETE CASCADE in schema handles documents
                result = await conn.execute(
                    "DELETE FROM knowledge_base_collections WHERE id = $1",
                    collection_id,
                )

                deleted = result != "DELETE 0"
                if deleted:
                    logger.info("Deleted collection: %s", collection_id)
                return deleted

    async def add_document(
        self, document: KnowledgeBaseDocument
    ) -> KnowledgeBaseDocument:
        """Add a document to a collection."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO knowledge_base_documents (
                        id, collection_id, filename, content_hash, file_size_bytes,
                        mime_type, content_preview, chunk_count, uploaded_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    document.id,
                    document.collection_id,
                    document.filename,
                    document.content_hash,
                    document.file_size_bytes,
                    document.mime_type,
                    document.content_preview,
                    document.chunk_count,
                    document.uploaded_at,
                )

                await conn.execute(
                    """
                    UPDATE knowledge_base_collections
                    SET document_count = document_count + 1,
                        total_size_bytes = total_size_bytes + $1,
                        updated_at = $2
                    WHERE id = $3
                    """,
                    document.file_size_bytes,
                    datetime.now(UTC),
                    document.collection_id,
                )

        logger.info("Added document: %s (%s)", document.filename, document.id)
        return document

    async def get_document(self, document_id: str) -> KnowledgeBaseDocument | None:
        """Get a document by ID."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM knowledge_base_documents WHERE id = $1",
                document_id,
            )
            return self._row_to_document(row) if row else None

    async def list_documents(self, collection_id: str) -> list[KnowledgeBaseDocument]:
        """List all documents in a collection."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM knowledge_base_documents WHERE collection_id = $1 ORDER BY uploaded_at DESC",
                collection_id,
            )
            return [self._row_to_document(row) for row in rows]

    async def delete_document(self, document_id: str) -> bool:
        """Delete a document."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                doc_row = await conn.fetchrow(
                    "SELECT collection_id, file_size_bytes FROM knowledge_base_documents WHERE id = $1",
                    document_id,
                )

                if not doc_row:
                    return False

                result = await conn.execute(
                    "DELETE FROM knowledge_base_documents WHERE id = $1",
                    document_id,
                )

                if result != "DELETE 0":
                    await conn.execute(
                        """
                        UPDATE knowledge_base_collections
                        SET document_count = document_count - 1,
                            total_size_bytes = total_size_bytes - $1,
                            updated_at = $2
                        WHERE id = $3
                        """,
                        doc_row["file_size_bytes"],
                        datetime.now(UTC),
                        doc_row["collection_id"],
                    )
                    logger.info("Deleted document: %s", document_id)
                    return True

                return False

    async def get_document_by_hash(
        self, content_hash: str
    ) -> KnowledgeBaseDocument | None:
        """Find a document by its content hash (for deduplication)."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM knowledge_base_documents WHERE content_hash = $1",
                content_hash,
            )
            return self._row_to_document(row) if row else None

    def _row_to_collection(self, row: asyncpg.Record) -> KnowledgeBaseCollection:
        return KnowledgeBaseCollection(
            id=str(row["id"]),
            user_id=str(row["user_id"]),
            name=row["name"],
            description=row["description"],
            document_count=row["document_count"],
            total_size_bytes=row["total_size_bytes"],
            created_at=row["created_at"].replace(tzinfo=UTC)
            if row["created_at"].tzinfo is None
            else row["created_at"],
            updated_at=row["updated_at"].replace(tzinfo=UTC)
            if row["updated_at"].tzinfo is None
            else row["updated_at"],
        )

    def _row_to_document(self, row: asyncpg.Record) -> KnowledgeBaseDocument:
        return KnowledgeBaseDocument(
            id=str(row["id"]),
            collection_id=str(row["collection_id"]),
            filename=row["filename"],
            content_hash=row["content_hash"],
            file_size_bytes=row["file_size_bytes"],
            mime_type=row["mime_type"],
            content_preview=row.get("content_preview"),
            chunk_count=row["chunk_count"],
            uploaded_at=row["uploaded_at"].replace(tzinfo=UTC)
            if row["uploaded_at"].tzinfo is None
            else row["uploaded_at"],
        )

