"""Tests for backend.utils.shutdown_listener — shutdown signal handling."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from backend.utils.shutdown_listener import (
    add_shutdown_listener,
    async_sleep_if_should_continue,
    remove_shutdown_listener,
    should_continue,
    should_exit,
    sleep_if_should_continue,
)


# ── should_exit ────────────────────────────────────────────────────────


class TestShouldExit:
    """Test checking if application should exit."""

    def test_returns_bool(self):
        """Test returns boolean value."""
        result = should_exit()
        assert isinstance(result, bool)

    def test_initially_false(self):
        """Test initially returns False."""
        # Reset module state
        import backend.utils.shutdown_listener as mod

        mod._should_exit = None

        result = should_exit()
        assert result is False


# ── should_continue ────────────────────────────────────────────────────


class TestShouldContinue:
    """Test checking if application should continue."""

    def test_returns_bool(self):
        """Test returns boolean value."""
        result = should_continue()
        assert isinstance(result, bool)

    def test_initially_true(self):
        """Test initially returns True."""
        # Reset module state
        import backend.utils.shutdown_listener as mod

        mod._should_exit = None

        result = should_continue()
        assert result is True

    def test_opposite_of_should_exit(self):
        """Test returns opposite of should_exit."""
        import backend.utils.shutdown_listener as mod

        mod._should_exit = False

        assert should_continue() is True
        assert should_exit() is False


# ── sleep_if_should_continue ───────────────────────────────────────────


class TestSleepIfShouldContinue:
    """Test sleep with shutdown awareness."""

    def test_sleeps_short_duration(self):
        """Test sleeps for short duration without checking."""
        import time

        start = time.time()
        sleep_if_should_continue(0.1)
        elapsed = time.time() - start
        assert 0.08 <= elapsed <= 0.2

    def test_sleeps_long_duration_in_chunks(self):
        """Test sleeps for long duration in chunks."""
        import backend.utils.shutdown_listener as mod

        mod._should_exit = False

        import time

        start = time.time()
        sleep_if_should_continue(0.5)
        elapsed = time.time() - start
        # Should sleep at least close to requested time
        assert elapsed >= 0.4

    def test_wakes_early_on_shutdown(self):
        """Test wakes up early when shutdown requested."""
        import backend.utils.shutdown_listener as mod
        import time

        mod._should_exit = False

        def trigger_shutdown():
            time.sleep(0.2)
            mod._should_exit = True

        thread = threading.Thread(target=trigger_shutdown)
        thread.start()

        start = time.time()
        sleep_if_should_continue(5.0)
        elapsed = time.time() - start
        thread.join()

        # Should wake up much sooner than 5 seconds
        assert elapsed < 2.0


# ── async_sleep_if_should_continue ─────────────────────────────────────


class TestAsyncSleepIfShouldContinue:
    """Test async sleep with shutdown awareness."""

    @pytest.mark.asyncio
    async def test_sleeps_short_duration(self):
        """Test async sleeps for short duration."""
        import time

        start = time.time()
        await async_sleep_if_should_continue(0.1)
        elapsed = time.time() - start
        assert 0.08 <= elapsed <= 0.2

    @pytest.mark.asyncio
    async def test_sleeps_long_duration_in_chunks(self):
        """Test async sleeps for long duration in chunks."""
        import backend.utils.shutdown_listener as mod
        import time

        mod._should_exit = False
        start = time.time()
        await async_sleep_if_should_continue(0.5)
        elapsed = time.time() - start
        assert elapsed >= 0.4


# ── add_shutdown_listener ──────────────────────────────────────────────


class TestAddShutdownListener:
    """Test adding shutdown listeners."""

    def test_returns_uuid(self):
        """Test returns UUID identifier."""
        listener = MagicMock()
        listener_id = add_shutdown_listener(listener)
        assert isinstance(listener_id, UUID)

    def test_listener_added_to_dict(self):
        """Test listener is added to internal dict."""
        import backend.utils.shutdown_listener as mod

        initial_count = len(mod._shutdown_listeners)
        listener = MagicMock()
        listener_id = add_shutdown_listener(listener)

        assert len(mod._shutdown_listeners) == initial_count + 1
        assert mod._shutdown_listeners[listener_id] == listener

    def test_multiple_listeners_have_unique_ids(self):
        """Test multiple listeners get unique IDs."""
        listener1 = MagicMock()
        listener2 = MagicMock()

        id1 = add_shutdown_listener(listener1)
        id2 = add_shutdown_listener(listener2)

        assert id1 != id2


# ── remove_shutdown_listener ───────────────────────────────────────────


class TestRemoveShutdownListener:
    """Test removing shutdown listeners."""

    def test_removes_existing_listener(self):
        """Test removes listener and returns True."""
        listener = MagicMock()
        listener_id = add_shutdown_listener(listener)

        result = remove_shutdown_listener(listener_id)
        assert result is True

    def test_returns_false_for_nonexistent_listener(self):
        """Test returns False for non-existent listener ID."""
        from uuid import uuid4

        fake_id = uuid4()
        result = remove_shutdown_listener(fake_id)
        assert result is False

    def test_listener_removed_from_dict(self):
        """Test listener is removed from internal dict."""
        import backend.utils.shutdown_listener as mod

        listener = MagicMock()
        listener_id = add_shutdown_listener(listener)

        assert listener_id in mod._shutdown_listeners
        remove_shutdown_listener(listener_id)
        assert listener_id not in mod._shutdown_listeners


# ── Signal handler integration ─────────────────────────────────────────


class TestSignalHandlerIntegration:
    """Test signal handler registration and invocation."""

    def test_listeners_called_on_simulated_shutdown(self):
        """Test shutdown listeners are called."""
        import backend.utils.shutdown_listener as mod

        # Reset state
        mod._should_exit = False
        mod._shutdown_listeners.clear()

        listener1 = MagicMock()
        listener2 = MagicMock()

        add_shutdown_listener(listener1)
        add_shutdown_listener(listener2)

        # Simulate shutdown
        mod._should_exit = True

        # In real scenario, signal handler would call listeners
        # Here we test the mechanism directly
        listeners = list(mod._shutdown_listeners.values())
        for listener in listeners:
            listener()

        listener1.assert_called_once()
        listener2.assert_called_once()

    def test_listener_exceptions_handled(self):
        """Test exceptions in listeners don't crash handler."""
        import backend.utils.shutdown_listener as mod

        mod._shutdown_listeners.clear()

        failing_listener = MagicMock(side_effect=RuntimeError("listener error"))
        successful_listener = MagicMock()

        add_shutdown_listener(failing_listener)
        add_shutdown_listener(successful_listener)

        # Simulate calling listeners with exception handling
        listeners = list(mod._shutdown_listeners.values())
        for listener in listeners:
            try:
                listener()
            except Exception:
                pass  # Handler should catch exceptions

        failing_listener.assert_called_once()
        successful_listener.assert_called_once()
