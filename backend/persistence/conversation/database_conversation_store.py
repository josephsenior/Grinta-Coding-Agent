"""Database-based conversation metadata storage implementation using PostgreSQL.

Stores conversation history and metrics in PostgreSQL for production use.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import asyncpg
from asyncpg import Pool

from backend.core.logger import forge_logger as logger
from backend.core.provider_types import ProviderType
from backend.persistence.conversation.conversation_store import ConversationStore
from backend.persistence.data_models.conversation_metadata import (
    ConversationMetadata,
    ConversationTrigger,
)
from backend.persistence.data_models.conversation_metadata_result_set import (
    ConversationMetadataResultSet,
)

if TYPE_CHECKING:
    from backend.core.config.forge_config import ForgeConfig

# SQL Schema for self-initialization
CONVERSATION_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS conversation_metadata (
    conversation_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    selected_repository TEXT,
    user_id TEXT,
    selected_branch TEXT,
    vcs_provider TEXT,
    last_updated_at TIMESTAMPTZ NOT NULL,
    trigger TEXT,
    pr_number JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL,
    llm_model TEXT,
    accumulated_cost DOUBLE PRECISION DEFAULT 0.0,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    name TEXT
);

CREATE INDEX IF NOT EXISTS idx_conv_user ON conversation_metadata(user_id);
CREATE INDEX IF NOT EXISTS idx_conv_updated ON conversation_metadata(last_updated_at DESC);

-- Agent Audit Table for observability
CREATE TABLE IF NOT EXISTS agent_audit (
    id SERIAL PRIMARY KEY,
    conversation_id TEXT REFERENCES conversation_metadata(conversation_id) ON DELETE CASCADE,
    user_id TEXT,
    task_name TEXT,
    status TEXT, -- 'success', 'failure', 'reverted'
    error_message TEXT,
    tokens_used INTEGER,
    cost DOUBLE PRECISION,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_conv ON agent_audit(conversation_id);
"""


class DatabaseConversationStore(ConversationStore):
    """PostgreSQL-based implementation of conversation storage."""

    def __init__(self, pool: Pool):
        """Initialize database conversation store.

        Args:
            pool: An initialized asyncpg connection pool.
        """
        self._pool = pool

    async def initialize(self) -> None:
        """Run startup creation of tables if they don't exist."""
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(CONVERSATION_SCHEMA_SQL)
                logger.info("Conversation database schema verified/initialized.")
        except Exception as e:
            logger.critical("Failed to initialize Conversation database schema: %s", e)
            raise

    async def save_metadata(self, metadata: ConversationMetadata) -> None:
        """Store conversation metadata."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO conversation_metadata (
                        conversation_id, title, selected_repository, user_id,
                        selected_branch, vcs_provider, last_updated_at, trigger,
                        pr_number, created_at, llm_model, accumulated_cost,
                        prompt_tokens, completion_tokens, total_tokens, name
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
                    ON CONFLICT (conversation_id) DO UPDATE SET
                        title = EXCLUDED.title,
                        selected_repository = EXCLUDED.selected_repository,
                        user_id = EXCLUDED.user_id,
                        selected_branch = EXCLUDED.selected_branch,
                        vcs_provider = EXCLUDED.vcs_provider,
                        last_updated_at = EXCLUDED.last_updated_at,
                        trigger = EXCLUDED.trigger,
                        pr_number = EXCLUDED.pr_number,
                        llm_model = EXCLUDED.llm_model,
                        accumulated_cost = EXCLUDED.accumulated_cost,
                        prompt_tokens = EXCLUDED.prompt_tokens,
                        completion_tokens = EXCLUDED.completion_tokens,
                        total_tokens = EXCLUDED.total_tokens,
                        name = EXCLUDED.name
                    """,
                    metadata.conversation_id,
                    metadata.title,
                    metadata.selected_repository,
                    metadata.user_id,
                    metadata.selected_branch,
                    metadata.vcs_provider.value if metadata.vcs_provider else None,
                    metadata.last_updated_at or datetime.now(UTC),
                    metadata.trigger.value if metadata.trigger else None,
                    json.dumps(metadata.pr_number),
                    metadata.created_at,
                    metadata.llm_model,
                    metadata.accumulated_cost,
                    metadata.prompt_tokens,
                    metadata.completion_tokens,
                    metadata.total_tokens,
                    metadata.name,
                )

    async def get_metadata(self, conversation_id: str) -> ConversationMetadata:
        """Load conversation metadata."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM conversation_metadata WHERE conversation_id = $1",
                conversation_id,
            )
            if not row:
                raise KeyError(f"Conversation {conversation_id} not found")
            return self._row_to_metadata(row)

    async def delete_metadata(self, conversation_id: str) -> None:
        """Delete conversation metadata."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM conversation_metadata WHERE conversation_id = $1",
                conversation_id,
            )

    async def delete_all_metadata(self) -> None:
        """Delete all conversation metadata."""
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM conversation_metadata")

    async def exists(self, conversation_id: str) -> bool:
        """Check if conversation exists."""
        async with self._pool.acquire() as conn:
            val = await conn.fetchval(
                "SELECT 1 FROM conversation_metadata WHERE conversation_id = $1",
                conversation_id,
            )
            return bool(val)

    async def search(
        self, page_id: str | None = None, limit: int = 20
    ) -> ConversationMetadataResultSet:
        """Search conversations with lightweight pagination."""
        offset = int(page_id) if page_id and page_id.isdigit() else 0

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM conversation_metadata
                ORDER BY last_updated_at DESC
                LIMIT $1 OFFSET $2
                """,
                limit + 1,
                offset,
            )

            results = [self._row_to_metadata(row) for row in rows[:limit]]
            next_page_id = str(offset + limit) if len(rows) > limit else None

            return ConversationMetadataResultSet(
                results=results, next_page_id=next_page_id
            )

    @classmethod
    async def get_instance(
        cls, config: ForgeConfig, user_id: str | None
    ) -> DatabaseConversationStore:
        """Get a store for the user represented by the token given."""
        from backend.persistence.database_pool import get_db_pool

        pool = await get_db_pool()
        return cls(pool=pool)

    def _row_to_metadata(self, row: asyncpg.Record) -> ConversationMetadata:
        pr_number = []
        if row["pr_number"]:
            if isinstance(row["pr_number"], str):
                pr_number = json.loads(row["pr_number"])
            else:
                pr_number = row["pr_number"]

        return ConversationMetadata(
            conversation_id=row["conversation_id"],
            title=row["title"],
            selected_repository=row["selected_repository"],
            user_id=row["user_id"],
            selected_branch=row["selected_branch"],
            vcs_provider=ProviderType(row["vcs_provider"])
            if row["vcs_provider"]
            else None,
            last_updated_at=row["last_updated_at"],
            trigger=ConversationTrigger(row["trigger"]) if row["trigger"] else None,
            pr_number=pr_number,
            created_at=row["created_at"],
            llm_model=row["llm_model"],
            accumulated_cost=row["accumulated_cost"],
            prompt_tokens=row["prompt_tokens"],
            completion_tokens=row["completion_tokens"],
            total_tokens=row["total_tokens"],
            name=row["name"],
        )

    # 🚀 Observability Extension: Log agent success/failure
    async def log_audit(
        self,
        conversation_id: str,
        task_name: str,
        status: str,
        error_message: str | None = None,
        tokens_used: int = 0,
        cost: float = 0.0,
        user_id: str | None = "oss_user",
    ) -> None:
        """Log agent activity for iterative improvement analysis."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO agent_audit (
                    conversation_id, user_id, task_name, status, error_message, tokens_used, cost
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                conversation_id,
                user_id,
                task_name,
                status,
                error_message,
                tokens_used,
                cost,
            )

