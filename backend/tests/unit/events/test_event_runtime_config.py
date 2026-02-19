"""Tests for backend.events.config — EventRuntimeDefaults and get_event_runtime_defaults."""

import os
from unittest.mock import patch

import pytest

from backend.events.config import EventRuntimeDefaults, get_event_runtime_defaults


class TestEventRuntimeDefaults:
    """Tests for the EventRuntimeDefaults frozen dataclass."""

    def test_default_values(self):
        defaults = EventRuntimeDefaults()
        assert defaults.max_queue_size == 2000
        assert defaults.drop_policy == "drop_oldest"
        assert defaults.hwm_ratio == 0.8
        assert defaults.block_timeout == 0.1
        assert defaults.rate_window_seconds == 60
        assert defaults.workers == 8
        assert defaults.async_write is False
        assert defaults.coalesce is False
        assert defaults.coalesce_window_ms == 100.0
        assert defaults.coalesce_max_batch == 20

    def test_custom_values(self):
        d = EventRuntimeDefaults(
            max_queue_size=500,
            drop_policy="reject",
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
        assert d.drop_policy == "reject"
        assert d.workers == 4
        assert d.async_write is True
        assert d.coalesce is True

    def test_frozen(self):
        d = EventRuntimeDefaults()
        with pytest.raises(AttributeError):
            d.max_queue_size = 999


class TestGetEventRuntimeDefaults:
    """Tests for get_event_runtime_defaults with env-var fallback."""

    def setup_method(self):
        # Clear the lru_cache between tests
        get_event_runtime_defaults.cache_clear()

    def teardown_method(self):
        get_event_runtime_defaults.cache_clear()

    @patch(
        "backend.core.config.utils.load_FORGE_config",
        side_effect=ImportError("no config"),
    )
    def test_env_var_fallback_defaults(self, mock_load):
        """When config load fails, use env var defaults."""
        with patch.dict(os.environ, {}, clear=False):
            # Remove any FORGE_ env vars that might be set
            env = {
                k: v for k, v in os.environ.items() if not k.startswith("FORGE_EVENT")
            }
            with patch.dict(os.environ, env, clear=True):
                result = get_event_runtime_defaults()
                assert result.max_queue_size == 2000
                assert result.drop_policy == "drop_oldest"
                assert result.workers == 8

    @patch(
        "backend.core.config.utils.load_FORGE_config", side_effect=RuntimeError("fail")
    )
    def test_env_var_custom_values(self, mock_load):
        """When config load fails, use custom env vars."""
        get_event_runtime_defaults.cache_clear()
        env = {
            "FORGE_EVENTSTREAM_MAX_QUEUE": "500",
            "FORGE_EVENTSTREAM_POLICY": "REJECT",
            "FORGE_EVENTSTREAM_HWM_RATIO": "0.95",
            "FORGE_EVENTSTREAM_BLOCK_TIMEOUT": "0.5",
            "FORGE_EVENTSTREAM_RATE_WINDOW_SECONDS": "30",
            "FORGE_EVENTSTREAM_WORKERS": "4",
            "FORGE_EVENTSTREAM_ASYNC_WRITE": "true",
            "FORGE_EVENT_COALESCE": "yes",
            "FORGE_EVENT_COALESCE_WINDOW_MS": "50",
            "FORGE_EVENT_COALESCE_MAX_BATCH": "10",
        }
        with patch.dict(os.environ, env, clear=True):
            result = get_event_runtime_defaults()
            assert result.max_queue_size == 500
            assert result.drop_policy == "reject"
            assert result.hwm_ratio == 0.95
            assert result.block_timeout == 0.5
            assert result.rate_window_seconds == 30
            assert result.workers == 4
            assert result.async_write is True
            assert result.coalesce is True
            assert result.coalesce_window_ms == 50.0
            assert result.coalesce_max_batch == 10

    @patch("backend.core.config.utils.load_FORGE_config", side_effect=Exception("fail"))
    def test_workers_minimum_one(self, mock_load):
        """Workers env value should be at least 1."""
        get_event_runtime_defaults.cache_clear()
        with patch.dict(os.environ, {"FORGE_EVENTSTREAM_WORKERS": "0"}, clear=True):
            result = get_event_runtime_defaults()
            assert result.workers == 1

    @patch("backend.core.config.utils.load_FORGE_config", side_effect=Exception("fail"))
    def test_coalesce_max_batch_minimum_one(self, mock_load):
        """coalesce_max_batch should be at least 1."""
        get_event_runtime_defaults.cache_clear()
        with patch.dict(
            os.environ, {"FORGE_EVENT_COALESCE_MAX_BATCH": "0"}, clear=True
        ):
            result = get_event_runtime_defaults()
            assert result.coalesce_max_batch == 1

    @patch("backend.core.config.utils.load_FORGE_config", side_effect=Exception("fail"))
    def test_async_write_false_values(self, mock_load):
        """async_write env values that are not truthy should be False."""
        get_event_runtime_defaults.cache_clear()
        with patch.dict(
            os.environ, {"FORGE_EVENTSTREAM_ASYNC_WRITE": "no"}, clear=True
        ):
            result = get_event_runtime_defaults()
            assert result.async_write is False

    def test_from_forge_config(self):
        """When load_FORGE_config succeeds with event_stream attribute, use it."""
        get_event_runtime_defaults.cache_clear()
        from types import SimpleNamespace

        event_cfg = SimpleNamespace(
            max_queue_size=1000,
            drop_policy="reject",
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
            "backend.core.config.utils.load_FORGE_config", return_value=mock_cfg
        ):
            result = get_event_runtime_defaults()
            assert result.max_queue_size == 1000
            assert result.drop_policy == "reject"
            assert result.workers == 16
            assert result.coalesce is True
            assert result.coalesce_max_batch == 50

    def test_from_forge_config_no_event_stream(self):
        """When config has no event_stream attribute, fall back to env vars."""
        get_event_runtime_defaults.cache_clear()
        from types import SimpleNamespace

        mock_cfg = SimpleNamespace()  # No event_stream attr

        with patch(
            "backend.core.config.utils.load_FORGE_config", return_value=mock_cfg
        ):
            with patch.dict(os.environ, {}, clear=True):
                result = get_event_runtime_defaults()
                assert result.max_queue_size == 2000  # default
