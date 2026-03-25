"""Tests for backend.storage.database_pool — async database pool utilities."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import backend.storage.database_pool as db_pool_module


@pytest.fixture(autouse=True)
def _reset_pool():
    """Reset the global pool state before and after each test."""
    db_pool_module._pool = None
    yield
    db_pool_module._pool = None


# ── get_db_pool ───────────────────────────────────────────────────────


class TestGetDbPool:
    async def test_raises_without_database_url(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(RuntimeError, match="DATABASE_URL is required"):
            await db_pool_module.get_db_pool()

    async def test_returns_existing_pool(self):
        sentinel = MagicMock()
        db_pool_module._pool = sentinel
        result = await db_pool_module.get_db_pool()
        assert result is sentinel

    async def test_creates_pool_with_default_sizes(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.delenv("DB_POOL_MIN_SIZE", raising=False)
        monkeypatch.delenv("DB_POOL_MAX_SIZE", raising=False)
        monkeypatch.delenv("DB_POOL_SIZE", raising=False)

        mock_pool = MagicMock()
        mock_asyncpg = MagicMock()
        mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)

        with patch(
            "builtins.__import__",
            side_effect=lambda name, *a, **kw: mock_asyncpg
            if name == "asyncpg"
            else __builtins__.__import__(name, *a, **kw),
        ):
            result = await db_pool_module.get_db_pool()

        assert result is mock_pool
        mock_asyncpg.create_pool.assert_awaited_once()
        call_kwargs = mock_asyncpg.create_pool.call_args[1]
        assert call_kwargs["min_size"] == 5
        assert call_kwargs["max_size"] == 20

    async def test_creates_pool_with_custom_sizes(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("DB_POOL_MIN_SIZE", "2")
        monkeypatch.setenv("DB_POOL_MAX_SIZE", "10")

        mock_pool = MagicMock()
        mock_asyncpg = MagicMock()
        mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)

        with patch(
            "builtins.__import__",
            side_effect=lambda name, *a, **kw: mock_asyncpg
            if name == "asyncpg"
            else __builtins__.__import__(name, *a, **kw),
        ):
            await db_pool_module.get_db_pool()

        call_kwargs = mock_asyncpg.create_pool.call_args[1]
        assert call_kwargs["min_size"] == 2
        assert call_kwargs["max_size"] == 10

    async def test_uses_db_pool_size_as_fallback(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.delenv("DB_POOL_MIN_SIZE", raising=False)
        monkeypatch.delenv("DB_POOL_MAX_SIZE", raising=False)
        monkeypatch.setenv("DB_POOL_SIZE", "8")

        mock_pool = MagicMock()
        mock_asyncpg = MagicMock()
        mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)

        with patch(
            "builtins.__import__",
            side_effect=lambda name, *a, **kw: mock_asyncpg
            if name == "asyncpg"
            else __builtins__.__import__(name, *a, **kw),
        ):
            await db_pool_module.get_db_pool()

        call_kwargs = mock_asyncpg.create_pool.call_args[1]
        assert call_kwargs["min_size"] == 8
        assert call_kwargs["max_size"] == 8


# ── close_db_pool ─────────────────────────────────────────────────────


class TestCloseDbPool:
    async def test_noop_when_no_pool(self):
        db_pool_module._pool = None
        await db_pool_module.close_db_pool()
        assert db_pool_module._pool is None

    async def test_closes_and_clears_pool(self):
        mock_pool = AsyncMock()
        db_pool_module._pool = mock_pool
        await db_pool_module.close_db_pool()
        mock_pool.close.assert_awaited_once()
        assert db_pool_module._pool is None

    async def test_clears_pool_even_on_close_error(self):
        mock_pool = AsyncMock()
        mock_pool.close.side_effect = RuntimeError("close failed")
        db_pool_module._pool = mock_pool
        with pytest.raises(RuntimeError):
            await db_pool_module.close_db_pool()
        # Pool should still be set to None even after error
        assert db_pool_module._pool is None

