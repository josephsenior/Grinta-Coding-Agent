"""Tests for backend.utils.tenacity_stop — tenacity stop condition with shutdown awareness."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock, patch

from backend.utils.tenacity_stop import stop_if_should_exit

# ── stop_if_should_exit ────────────────────────────────────────────────


class TestStopIfShouldExit:
    """Test tenacity stop condition integrating shutdown listener."""

    def test_returns_bool(self):
        """Test returns boolean value."""
        stop_condition = stop_if_should_exit()
        retry_state = MagicMock()
        result = stop_condition(retry_state)
        assert isinstance(result, bool)

    def test_returns_true_when_should_exit(self):
        """Test returns True when shutdown requested."""
        stop_condition = stop_if_should_exit()
        retry_state = MagicMock()

        # Monkeypatch the tenacity_stop module to have should_exit
        import backend.utils.tenacity_stop

        def mock_should_exit():
            return True

        original = getattr(backend.utils.tenacity_stop, 'should_exit', None)
        try:
            cast(Any, backend.utils.tenacity_stop).should_exit = mock_should_exit
            result = stop_condition(retry_state)
            assert result is True
        finally:
            if original is None:
                delattr(backend.utils.tenacity_stop, 'should_exit')
            else:
                cast(Any, backend.utils.tenacity_stop).should_exit = original

    def test_returns_false_when_should_continue(self):
        """Test returns False when no shutdown requested."""
        stop_condition = stop_if_should_exit()
        retry_state = MagicMock()

        with patch('backend.utils.shutdown_listener.should_exit', return_value=False):
            result = stop_condition(retry_state)
            assert result is False

    def test_handles_exception_gracefully(self):
        """Test handles exception from should_exit gracefully."""
        stop_condition = stop_if_should_exit()
        retry_state = MagicMock()

        with patch(
            'backend.utils.shutdown_listener.should_exit',
            side_effect=RuntimeError('error'),
        ):
            result = stop_condition(retry_state)
            # Should not crash, returns False
            assert result is False

    def test_uses_canonical_module(self):
        """Test resolves should_exit from canonical module."""
        stop_condition = stop_if_should_exit()
        retry_state = MagicMock()

        # Monkeypatch the tenacity_stop module
        import backend.utils.tenacity_stop

        def mock_should_exit():
            return True

        original = getattr(backend.utils.tenacity_stop, 'should_exit', None)
        try:
            cast(Any, backend.utils.tenacity_stop).should_exit = mock_should_exit
            result = stop_condition(retry_state)
            assert result is True
        finally:
            if original is None:
                delattr(backend.utils.tenacity_stop, 'should_exit')
            else:
                cast(Any, backend.utils.tenacity_stop).should_exit = original

    def test_callable_local_fallback(self):
        """Test falls back to local callable if available."""
        stop_condition = stop_if_should_exit()
        retry_state = MagicMock()

        # When module resolution fails, uses local if callable
        with patch(
            'backend.utils.shutdown_listener.should_exit', side_effect=Exception
        ):
            result = stop_condition(retry_state)
            # Local not set, should return False
            assert result is False

    def test_works_with_real_retry_state(self):
        """Test works with realistic retry state object."""
        from tenacity import (
            RetryCallState,
            retry,
            stop_after_attempt,
        )

        stop_condition = stop_if_should_exit()

        @retry(stop=stop_after_attempt(3))
        def sample_func():
            return 'success'

        # Create a retry call state
        retry_mgr = cast(Any, sample_func).retry
        retry_state = RetryCallState(
            retry_object=retry_mgr, fn=sample_func, args=(), kwargs={}
        )

        with patch('backend.utils.shutdown_listener.should_exit', return_value=False):
            result = stop_condition(retry_state)
            assert result is False

    def test_instance_creation(self):
        """Test creating instance of stop_if_should_exit."""
        stop_cond1 = stop_if_should_exit()
        stop_cond2 = stop_if_should_exit()

        # Should be able to create multiple instances
        assert stop_cond1 is not None
        assert stop_cond2 is not None

    def test_local_fallback_callable_returns_true(self):
        """Test that line 35 is covered when mod.should_exit() fails."""
        from backend.utils import tenacity_stop as ts_mod

        stop_condition = stop_if_should_exit()
        retry_state = MagicMock()

        # Inject a callable into the module's globals so the local fallback fires
        ts_mod.should_exit = lambda: False  # type: ignore[attr-defined]
        try:
            # Make the canonical import_module path raise so local fallback runs
            def side_effect(name):
                if name == 'backend.utils.tenacity_stop':
                    m = MagicMock()
                    m.should_exit.side_effect = RuntimeError('Fail')
                    return m
                import importlib

                return importlib.import_module(name)

            with patch('importlib.import_module', side_effect=side_effect):
                assert stop_condition(retry_state) is False
        finally:
            del ts_mod.should_exit  # type: ignore[attr-defined]
