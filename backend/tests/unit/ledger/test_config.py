"""Tests for backend.ledger.config — event subsystem configuration."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from backend.ledger.config import EventRuntimeDefaults, get_event_runtime_defaults


def _assert_event_runtime_attrs(
    defaults: EventRuntimeDefaults, expected: dict[str, object]
) -> None:
    for attr, value in expected.items():
        assert getattr(defaults, attr) == value

# ── EventRuntimeDefaults dataclass ─────────────────────────────────────


class TestEventRuntimeDefaults:
    """Test EventRuntimeDefaults configuration dataclass."""

    def test_creates_with_defaults(self):
        """Test creating EventRuntimeDefaults with default values."""
        defaults = EventRuntimeDefaults()
        _assert_event_runtime_attrs(
            defaults,
            {
                'max_queue_size': 2000,
                'drop_policy': 'drop_oldest',
                'hwm_ratio': 0.8,
                'block_timeout': 0.1,
                'rate_window_seconds': 60,
                'workers': 1,
                'async_write': False,
                'coalesce': False,
                'coalesce_window_ms': 100.0,
                'coalesce_max_batch': 20,
            },
        )

    def test_creates_with_custom_values(self):
        """Test creating EventRuntimeDefaults with custom values."""
        defaults = EventRuntimeDefaults(
            max_queue_size=5000,
            drop_policy='block',
            hwm_ratio=0.9,
            block_timeout=0.5,
            rate_window_seconds=120,
            workers=16,
            async_write=True,
            coalesce=True,
            coalesce_window_ms=200.0,
            coalesce_max_batch=50,
        )
        _assert_event_runtime_attrs(
            defaults,
            {
                'max_queue_size': 5000,
                'drop_policy': 'block',
                'hwm_ratio': 0.9,
                'block_timeout': 0.5,
                'rate_window_seconds': 120,
                'workers': 16,
                'async_write': True,
                'coalesce': True,
                'coalesce_window_ms': 200.0,
                'coalesce_max_batch': 50,
            },
        )

    def test_is_frozen(self):
        """Test EventRuntimeDefaults is immutable."""
        defaults = EventRuntimeDefaults()
        with pytest.raises(FrozenInstanceError):
            cast(Any, defaults).max_queue_size = 3000


# ── get_event_runtime_defaults function ────────────────────────────────


class TestGetEventRuntimeDefaults:
    """Test configuration resolution with config file and env fallback."""

    def setup_method(self):
        """Clear LRU cache before each test."""
        get_event_runtime_defaults.cache_clear()

    def teardown_method(self):
        """Clear LRU cache after each test."""
        get_event_runtime_defaults.cache_clear()

    @patch('backend.core.config.config_loader.load_app_config')
    def test_loads_from_app_config(self, mock_load_config):
        """Test loads configuration from App config file."""
        # Mock config with event_stream section
        mock_config = MagicMock()
        mock_event_cfg = MagicMock()
        mock_event_cfg.max_queue_size = 3000
        mock_event_cfg.drop_policy = 'block'
        mock_event_cfg.hwm_ratio = 0.9
        mock_event_cfg.block_timeout = 0.2
        mock_event_cfg.rate_window_seconds = 90
        mock_event_cfg.workers = 12
        mock_event_cfg.async_write = True
        mock_event_cfg.coalesce = True
        mock_event_cfg.coalesce_window_ms = 150.0
        mock_event_cfg.coalesce_max_batch = 30
        mock_config.event_stream = mock_event_cfg
        mock_load_config.return_value = mock_config

        defaults = get_event_runtime_defaults()
        _assert_event_runtime_attrs(
            defaults,
            {
                'max_queue_size': 3000,
                'drop_policy': 'block',
                'hwm_ratio': 0.9,
                'block_timeout': 0.2,
                'rate_window_seconds': 90,
                'workers': 12,
                'async_write': True,
                'coalesce': True,
                'coalesce_window_ms': 150.0,
                'coalesce_max_batch': 30,
            },
        )

    @patch('backend.core.config.config_loader.load_app_config')
    def test_returns_defaults_when_no_event_stream_section(self, mock_load_config):
        """Test returns built-in defaults when config has no event_stream section."""
        mock_config = MagicMock()
        mock_config.event_stream = None
        mock_load_config.return_value = mock_config

        defaults = get_event_runtime_defaults()

        # Should use environment defaults
        assert defaults.max_queue_size == 2000  # default from env

    @patch('backend.core.config.config_loader.load_app_config', side_effect=ImportError)
    def test_falls_back_to_env_on_config_load_error(self, mock_load_config):
        """Test falls back to environment variables on config load error."""
        defaults = get_event_runtime_defaults()

        # Should use environment defaults
        assert isinstance(defaults, EventRuntimeDefaults)

    def test_loads_from_environment_variables(self, monkeypatch):
        """Test loads configuration from environment variables."""
        get_event_runtime_defaults.cache_clear()
        monkeypatch.setenv('APP_EVENTSTREAM_MAX_QUEUE', '4000')
        monkeypatch.setenv('APP_EVENTSTREAM_POLICY', 'BLOCK')
        monkeypatch.setenv('APP_EVENTSTREAM_HWM_RATIO', '0.75')
        monkeypatch.setenv('APP_EVENTSTREAM_BLOCK_TIMEOUT', '0.3')
        monkeypatch.setenv('APP_EVENTSTREAM_RATE_WINDOW_SECONDS', '45')
        monkeypatch.setenv('APP_EVENTSTREAM_WORKERS', '4')
        monkeypatch.setenv('APP_EVENTSTREAM_ASYNC_WRITE', 'true')
        monkeypatch.setenv('APP_EVENT_COALESCE', 'yes')
        monkeypatch.setenv('APP_EVENT_COALESCE_WINDOW_MS', '250')
        monkeypatch.setenv('APP_EVENT_COALESCE_MAX_BATCH', '40')

        # Patch config loading to fail so we use env vars
        with patch(
            'backend.core.config.config_loader.load_app_config', side_effect=Exception
        ):
            defaults = get_event_runtime_defaults()
        _assert_event_runtime_attrs(
            defaults,
            {
                'max_queue_size': 4000,
                'drop_policy': 'block',
                'hwm_ratio': 0.75,
                'block_timeout': 0.3,
                'rate_window_seconds': 45,
                'workers': 4,
                'async_write': True,
                'coalesce': True,
                'coalesce_window_ms': 250.0,
                'coalesce_max_batch': 40,
            },
        )

    def test_coalesce_bool_parsing(self, monkeypatch):
        """Test coalesce boolean environment parsing."""
        get_event_runtime_defaults.cache_clear()

        with patch(
            'backend.core.config.config_loader.load_app_config', side_effect=Exception
        ):
            # Test "1"
            monkeypatch.setenv('APP_EVENT_COALESCE', '1')
            assert get_event_runtime_defaults().coalesce is True
            get_event_runtime_defaults.cache_clear()

            # Test "false"
            monkeypatch.setenv('APP_EVENT_COALESCE', 'false')
            assert get_event_runtime_defaults().coalesce is False
            get_event_runtime_defaults.cache_clear()

    def test_async_write_bool_parsing(self, monkeypatch):
        """Test async_write boolean environment parsing."""
        get_event_runtime_defaults.cache_clear()

        with patch(
            'backend.core.config.config_loader.load_app_config', side_effect=Exception
        ):
            # Test "yes"
            monkeypatch.setenv('APP_EVENTSTREAM_ASYNC_WRITE', 'yes')
            assert get_event_runtime_defaults().async_write is True
            get_event_runtime_defaults.cache_clear()

            # Test "0"
            monkeypatch.setenv('APP_EVENTSTREAM_ASYNC_WRITE', '0')
            assert get_event_runtime_defaults().async_write is False
            get_event_runtime_defaults.cache_clear()

    def test_workers_minimum_enforced(self, monkeypatch):
        """Test workers minimum of 1 is enforced."""
        get_event_runtime_defaults.cache_clear()
        monkeypatch.setenv('APP_EVENTSTREAM_WORKERS', '0')

        with patch(
            'backend.core.config.config_loader.load_app_config', side_effect=Exception
        ):
            defaults = get_event_runtime_defaults()

        assert defaults.workers == 1  # minimum

    def test_coalesce_max_batch_minimum_enforced(self, monkeypatch):
        """Test coalesce_max_batch minimum of 1 is enforced."""
        get_event_runtime_defaults.cache_clear()
        monkeypatch.setenv('APP_EVENT_COALESCE_MAX_BATCH', '-5')

        with patch(
            'backend.core.config.config_loader.load_app_config', side_effect=Exception
        ):
            defaults = get_event_runtime_defaults()

        assert defaults.coalesce_max_batch == 1  # minimum

    def test_caches_result(self):
        """Test result is cached via lru_cache."""
        defaults1 = get_event_runtime_defaults()
        defaults2 = get_event_runtime_defaults()

        # Should be same instance due to caching
        assert defaults1 is defaults2

    @patch('backend.core.config.config_loader.load_app_config')
    def test_uses_getattr_fallbacks_for_missing_attributes(self, mock_load_config):
        """Test uses default values when config attributes are missing."""
        mock_config = MagicMock()
        mock_event_cfg = MagicMock()
        # Only set some attributes
        mock_event_cfg.max_queue_size = 5000
        # Other attributes will use getattr defaults
        del mock_event_cfg.drop_policy
        mock_config.event_stream = mock_event_cfg
        mock_load_config.return_value = mock_config

        defaults = get_event_runtime_defaults()

        assert defaults.max_queue_size == 5000
        assert defaults.drop_policy == 'drop_oldest'  # fallback default
