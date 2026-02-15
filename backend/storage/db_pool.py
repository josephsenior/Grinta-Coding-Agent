"""Async database pool utilities.

Database-backed stores in Forge (e.g., conversation and knowledge base stores)
expect an async pool exposing an asyncpg-like API (`acquire()`, `transaction()`,
`execute()`, etc.).

This module provides a shared global pool created from `DATABASE_URL`.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from backend.core.logger import FORGE_logger as logger

_pool: Any | None = None
_pool_lock = asyncio.Lock()


async def get_db_pool() -> Any:
    """Get or create the shared database pool.

    Requires `DATABASE_URL` to be set when database-backed storage is enabled.
    """

    global _pool
    if _pool is not None:
        return _pool

    async with _pool_lock:
        # Double-checked locking: re-read global after acquiring lock
        # Use getattr to prevent mypy from narrowing _pool to None
        # after the check outside the lock (another coroutine may have set it).
        current: Any | None = globals().get("_pool")
        if current is not None:
            return current

        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError(
                "DATABASE_URL is required when using database-backed storage"
            )

        min_size = int(os.getenv("DB_POOL_MIN_SIZE", os.getenv("DB_POOL_SIZE", "5")))
        max_size = int(os.getenv("DB_POOL_MAX_SIZE", os.getenv("DB_POOL_SIZE", "20")))

        asyncpg = __import__("asyncpg")
        _pool = await asyncpg.create_pool(
            dsn=database_url, min_size=min_size, max_size=max_size
        )

        logger.info(
            "Database pool initialized: min_size=%s max_size=%s", min_size, max_size
        )
        return _pool


async def close_db_pool() -> None:
    """Close the shared pool if it exists."""

    global _pool
    if _pool is None:
        return

    try:
        await _pool.close()
    finally:
        _pool = None
