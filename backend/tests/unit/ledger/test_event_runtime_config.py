"""Tests for backend.ledger.config — EventRuntimeDefaults and get_event_runtime_defaults."""

import os
from typing import Any, cast
from unittest.mock import patch

import pytest

from backend.ledger.config import EventRuntimeDefaults, get_event_runtime_defaults


def _assert_event_runtime_attrs(obj: EventRuntimeDefaults, expected: dict[str, object]) -> None:
    for attr, value in expected.items():
        assert getattr(obj, attr) == value


class TestEventRuntimeDefaults:
    """Tests for the EventRuntimeDefaults frozen dataclass."""

    def test_default_values(self):
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

    def test_custom_values(self):
        d = EventRuntimeDefaults(
            max_queue_size=500,
            drop_policy='reject',
            hwm_ratio=0.9,
            block_timeout=0.5,
            rate_window_seconds=30,
            workers=4,
            async_write=True,
            coalesce=True,
            coalesce_window_ms=50.0,
            coalesce_max_batch=10,
        )
        assert d.max_queue_size == 500
        assert d.drop_policy == 'reject'
        assert d.workers == 4
        assert d.async_write is True
        assert d.coalesce is True

    def test_frozen(self):
        d = EventRuntimeDefaults()
        with pytest.raises(AttributeError):
            cast(Any, d).max_queue_size = 999


class TestGetEventRuntimeDefaults:
    """Tests for get_event_runtime_defaults with env-var fallback."""

    def setup_method(self):
        # Clear the lru_cache between tests
        get_event_runtime_defaults.cache_clear()

    def teardown_method(self):
        get_event_runtime_defaults.cache_clear()

    @patch(
        'backend.core.config.config_loader.load_app_config',
        side_effect=ImportError('no config'),
    )
    def test_env_var_fallback_defaults(self, mock_load):
        """When config load fails, use env var defaults."""
        with patch.dict(os.environ, {}, clear=False):
            # Remove any APP_ env vars that might be set
            env = {k: v for k, v in os.environ.items() if not k.startswith('APP_EVENT')}
            with patch.dict(os.environ, env, clear=True):
                result = get_event_runtime_defaults()
                assert result.max_queue_size == 2000
                assert result.drop_policy == 'drop_oldest'
                assert result.workers == 1

    @patch(
        'backend.core.config.config_loader.load_app_config',
        side_effect=RuntimeError('fail'),
    )
    def test_env_var_custom_values(self, mock_load):
        """When config load fails, use custom env vars."""
        get_event_runtime_defaults.cache_clear()
        env = {
            'APP_EVENTSTREAM_MAX_QUEUE': '500',
            'APP_EVENTSTREAM_POLICY': 'REJECT',
            'APP_EVENTSTREAM_HWM_RATIO': '0.95',
            'APP_EVENTSTREAM_BLOCK_TIMEOUT': '0.5',
            'APP_EVENTSTREAM_RATE_WINDOW_SECONDS': '30',
            'APP_EVENTSTREAM_WORKERS': '4',
            'APP_EVENTSTREAM_ASYNC_WRITE': 'true',
            'APP_EVENT_COALESCE': 'yes',
            'APP_EVENT_COALESCE_WINDOW_MS': '50',
            'APP_EVENT_COALESCE_MAX_BATCH': '10',
        }
        with patch.dict(os.environ, env, clear=True):
            result = get_event_runtime_defaults()
            _assert_event_runtime_attrs(
                result,
                {
                    'max_queue_size': 500,
                    'drop_policy': 'reject',
                    'hwm_ratio': 0.95,
                    'block_timeout': 0.5,
                    'rate_window_seconds': 30,
                    'workers': 4,
                    'async_write': True,
                    'coalesce': True,
                    'coalesce_window_ms': 50.0,
                    'coalesce_max_batch': 10,
                },
            )

    @patch(
        'backend.core.config.config_loader.load_app_config',
        side_effect=Exception('fail'),
    )
    def test_workers_minimum_one(self, mock_load):
        """Workers env value should be at least 1."""
        get_event_runtime_defaults.cache_clear()
        with patch.dict(os.environ, {'APP_EVENTSTREAM_WORKERS': '0'}, clear=True):
            result = get_event_runtime_defaults()
            assert result.workers == 1

    @patch(
        'backend.core.config.config_loader.load_app_config',
        side_effect=Exception('fail'),
    )
    def test_coalesce_max_batch_minimum_one(self, mock_load):
        """coalesce_max_batch should be at least 1."""
        get_event_runtime_defaults.cache_clear()
        with patch.dict(os.environ, {'APP_EVENT_COALESCE_MAX_BATCH': '0'}, clear=True):
            result = get_event_runtime_defaults()
            assert result.coalesce_max_batch == 1

    @patch(
        'backend.core.config.config_loader.load_app_config',
        side_effect=Exception('fail'),
    )
    def test_async_write_false_values(self, mock_load):
        """async_write env values that are not truthy should be False."""
        get_event_runtime_defaults.cache_clear()
        with patch.dict(os.environ, {'APP_EVENTSTREAM_ASYNC_WRITE': 'no'}, clear=True):
            result = get_event_runtime_defaults()
            assert result.async_write is False

    def test_from_app_config(self):
        """When load_app_config succeeds with event_stream attribute, use it."""
        get_event_runtime_defaults.cache_clear()
        from types import SimpleNamespace

        event_cfg = SimpleNamespace(
            max_queue_size=1000,
            drop_policy='reject',
            hwm_ratio=0.7,
            block_timeout=0.2,
            rate_window_seconds=120,
            workers=16,
            async_write=True,
            coalesce=True,
            coalesce_window_ms=200.0,
            coalesce_max_batch=50,
        )
        mock_cfg = SimpleNamespace(event_stream=event_cfg)

        with patch(
            'backend.core.config.config_loader.load_app_config', return_value=mock_cfg
        ):
            result = get_event_runtime_defaults()
            assert result.max_queue_size == 1000
            assert result.drop_policy == 'reject'
            assert result.workers == 16
            assert result.coalesce is True
            assert result.coalesce_max_batch == 50

    def test_from_app_config_no_event_stream(self):
        """When config has no event_stream attribute, fall back to env vars."""
        get_event_runtime_defaults.cache_clear()
        from types import SimpleNamespace

        mock_cfg = SimpleNamespace()  # No event_stream attr

        with patch(
            'backend.core.config.config_loader.load_app_config', return_value=mock_cfg
        ):
            with patch.dict(os.environ, {}, clear=True):
                result = get_event_runtime_defaults()
                assert result.max_queue_size == 2000  # default
