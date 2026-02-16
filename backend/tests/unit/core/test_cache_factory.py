"""Tests for backend.core.cache.factory — Distributed cache factory."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from backend.core.cache.factory import create_distributed_cache


class TestCreateDistributedCache:
    """Tests for the create_distributed_cache factory function."""

    @patch("backend.core.cache.factory.DISTRIBUTED_CACHE_AVAILABLE", False)
    def test_returns_none_when_unavailable(self):
        result = create_distributed_cache(prefix="test", ttl_seconds=300)
        assert result is None

    @patch("backend.core.cache.factory.DISTRIBUTED_CACHE_AVAILABLE", True)
    @patch("backend.core.cache.factory.DistributedCache")
    def test_returns_cache_when_enabled(self, mock_cls):
        instance = MagicMock()
        instance.enabled = True
        mock_cls.return_value = instance

        result = create_distributed_cache(
            prefix="llm", ttl_seconds=600, max_connections=25
        )
        assert result is instance
        mock_cls.assert_called_once_with(
            prefix="llm",
            ttl_seconds=600,
            max_connections=25,
        )

    @patch("backend.core.cache.factory.DISTRIBUTED_CACHE_AVAILABLE", True)
    @patch("backend.core.cache.factory.DistributedCache")
    def test_returns_none_when_not_enabled(self, mock_cls):
        instance = MagicMock()
        instance.enabled = False
        mock_cls.return_value = instance

        result = create_distributed_cache(prefix="test", ttl_seconds=300)
        assert result is None

    @patch("backend.core.cache.factory.DISTRIBUTED_CACHE_AVAILABLE", True)
    @patch("backend.core.cache.factory.DistributedCache")
    def test_returns_none_on_exception(self, mock_cls):
        mock_cls.side_effect = RuntimeError("Redis down")
        result = create_distributed_cache(prefix="test", ttl_seconds=300)
        assert result is None

    @patch("backend.core.cache.factory.DISTRIBUTED_CACHE_AVAILABLE", True)
    @patch("backend.core.cache.factory.DistributedCache")
    def test_default_max_connections(self, mock_cls):
        instance = MagicMock()
        instance.enabled = True
        mock_cls.return_value = instance

        create_distributed_cache(prefix="x", ttl_seconds=60)
        _, kwargs = mock_cls.call_args
        assert kwargs["max_connections"] == 50
