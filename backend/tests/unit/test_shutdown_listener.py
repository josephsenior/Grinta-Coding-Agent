"""Tests for backend.utils.shutdown_listener — shutdown signal handling."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

# We must be careful not to actually register signal handlers in tests.
# We'll test the listener registry and helpers with the module-level state patched.

import backend.utils.shutdown_listener as sl


class TestShutdownListenerRegistry:
    """Tests for add_shutdown_listener / remove_shutdown_listener."""

    def setup_method(self):
        self._orig_listeners = sl._shutdown_listeners.copy()

    def teardown_method(self):
        sl._shutdown_listeners.clear()
        sl._shutdown_listeners.update(self._orig_listeners)

    def test_add_listener_returns_uuid(self):
        uid = sl.add_shutdown_listener(lambda: None)
        assert isinstance(uid, UUID)

    def test_listener_registered(self):
        cb = MagicMock()
        uid = sl.add_shutdown_listener(cb)
        assert uid in sl._shutdown_listeners
        assert sl._shutdown_listeners[uid] is cb

    def test_remove_listener(self):
        uid = sl.add_shutdown_listener(lambda: None)
        removed = sl.remove_shutdown_listener(uid)
        assert removed is True
        assert uid not in sl._shutdown_listeners

    def test_remove_nonexistent_returns_false(self):
        from uuid import uuid4
        assert sl.remove_shutdown_listener(uuid4()) is False

    def test_multiple_listeners(self):
        ids = [sl.add_shutdown_listener(lambda: None) for _ in range(5)]
        assert len(ids) == 5
        assert len(set(ids)) == 5  # all unique


class TestShouldExitHelpers:
    """Tests for should_exit / should_continue with mocked state."""

    def test_should_exit_false(self):
        with patch.object(sl, "_should_exit", False), \
             patch.object(sl, "_register_signal_handlers"):
            assert sl.should_exit() is False

    def test_should_exit_true(self):
        with patch.object(sl, "_should_exit", True), \
             patch.object(sl, "_register_signal_handlers"):
            assert sl.should_exit() is True

    def test_should_continue_true(self):
        with patch.object(sl, "_should_exit", False), \
             patch.object(sl, "_register_signal_handlers"):
            assert sl.should_continue() is True

    def test_should_continue_false(self):
        with patch.object(sl, "_should_exit", True), \
             patch.object(sl, "_register_signal_handlers"):
            assert sl.should_continue() is False


class TestSleepHelpers:
    """Tests for sleep helpers (short durations)."""

    def test_sleep_if_should_continue_short(self):
        """For delay <= 1, the function uses time.sleep directly."""
        with patch.object(sl, "_should_exit", True), \
             patch.object(sl, "_register_signal_handlers"), \
             patch("backend.utils.shutdown_listener.time") as mock_time:
            mock_time.time.return_value = 100.0
            mock_time.sleep = MagicMock()
            sl.sleep_if_should_continue(0.5)
            mock_time.sleep.assert_called_once_with(0.5)

    async def test_async_sleep_short(self):
        """For delay <= 1, the function uses asyncio.sleep directly."""
        with patch.object(sl, "_should_exit", True), \
             patch.object(sl, "_register_signal_handlers"), \
             patch("backend.utils.shutdown_listener.asyncio") as mock_asyncio:
            mock_asyncio.sleep = MagicMock(return_value=MagicMock())
            # Make the mock awaitable
            import asyncio
            future = asyncio.get_event_loop().create_future()
            future.set_result(None)
            mock_asyncio.sleep.return_value = future
            await sl.async_sleep_if_should_continue(0.5)
            mock_asyncio.sleep.assert_called_once_with(0.5)
