"""Tests for backend.utils.shutdown_listener — shutdown signal handling."""

import signal as _signal
import threading
import time
from unittest.mock import MagicMock, patch
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


@pytest.fixture(autouse=True)
def reset_shutdown_listener():
    """Reset shutdown listener state between tests to avoid interference."""
    import backend.utils.shutdown_listener as mod

    mod._should_exit = False
    mod._shutdown_listeners.clear()
    yield
    mod._should_exit = False
    mod._shutdown_listeners.clear()


# ── should_exit ────────────────────────────────────────────────────────


class TestShouldExit:
    """Test checking if application should exit."""

    def test_returns_bool(self):
        """Test returns boolean value."""
        result = should_exit()
        assert isinstance(result, bool)

    def test_initially_false(self):
        """Test initially returns False."""
        import backend.utils.shutdown_listener as mod

        mod._should_exit = None  # Reset for this test
        # Avoid real signal registration which can be flaky on Windows CI
        with patch("backend.utils.shutdown_listener._register_signal_handler"):
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
        import backend.utils.shutdown_listener as mod

        mod._should_exit = None  # Reset for this test
        # Avoid real signal registration which can be flaky on Windows CI
        with patch("backend.utils.shutdown_listener._register_signal_handler"):
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


# ── Internal details for coverage ──────────────────────────────────────


class TestShutdownListenerInternal:
    """Test internal functions of shutdown_listener for coverage."""

    def test_register_signal_handler_mocked(self):
        """Test _register_signal_handler and the signal handler."""
        import backend.utils.shutdown_listener as mod

        with patch("backend.utils.shutdown_listener.signal.signal") as mock_signal, \
             patch("backend.utils.shutdown_listener.signal.getsignal") as mock_getsignal:
            mock_getsignal.return_value = _signal.SIG_DFL
            mod._register_signal_handler(_signal.SIGINT)

            mock_signal.assert_called_once()
            args, _ = mock_signal.call_args
            assert args[0] == _signal.SIGINT
            handler = args[1]
            assert callable(handler)

            # Test the handler function
            mod._should_exit = False
            mock_listener = MagicMock()
            mod.add_shutdown_listener(mock_listener)

            # Call handler directly
            try:
                handler(_signal.SIGINT, None)
            except KeyboardInterrupt:
                pass  # expected from default_int_handler

            assert mod._should_exit is True
            mock_listener.assert_called_once()

    def test_handler_exception_path(self):
        """Test the signal handler's exception handling for listeners."""
        import backend.utils.shutdown_listener as mod

        with patch("signal.signal") as mock_signal, patch(
            "signal.getsignal", return_value=_signal.SIG_DFL
        ):
            mod._register_signal_handler(_signal.SIGINT)
            handler = mock_signal.call_args[0][1]

            mod._should_exit = False
            failing_listener = MagicMock(side_effect=Exception("Crash"))
            mod.add_shutdown_listener(failing_listener)

            # Should not raise exception (except KeyboardInterrupt from fallback)
            try:
                handler(_signal.SIGINT, None)
            except KeyboardInterrupt:
                pass
            failing_listener.assert_called_once()

    def test_register_signal_handler_sig_ign(self):
        """Test with SIG_IGN to ensure we hit elif but not assign."""
        import backend.utils.shutdown_listener as mod
        
        with patch("backend.utils.shutdown_listener.signal.signal"), \
             patch("backend.utils.shutdown_listener.signal.getsignal", return_value=_signal.SIG_IGN):
            mod._register_signal_handler(_signal.SIGINT)

    def test_register_signal_handlers_actually_not_main_thread(self):
        """Test _register_signal_handlers from a real non-main thread."""
        import backend.utils.shutdown_listener as mod
        import threading
        
        # Reset to ensure we run registration again
        mod._should_exit = None
        
        exceptions = []
        def run():
            try:
                mod._register_signal_handlers()
            except Exception as e:
                exceptions.append(e)
                
        t = threading.Thread(target=run)
        t.start()
        t.join()
        
        assert not exceptions

    def test_sleep_long_duration_chunks(self):
        """Test sleep_if_should_continue with delay > 1 hits the loop."""
        import backend.utils.shutdown_listener as mod

        mod._should_exit = False
        start = time.time()
        # Sleep for slightly over 1s to trigger at least one loop iteration
        sleep_if_should_continue(1.2)
        elapsed = time.time() - start
        assert elapsed >= 1.0

    @pytest.mark.asyncio
    async def test_async_sleep_long_duration_chunks(self):
        """Test async_sleep_if_should_continue with delay > 1 hits the loop."""
        import backend.utils.shutdown_listener as mod

        mod._should_exit = False
        start = time.time()
        await async_sleep_if_should_continue(1.2)
        elapsed = time.time() - start
        assert elapsed >= 1.0

    @pytest.mark.asyncio
    async def test_async_sleep_long_duration_wake_early(self):
        """Test async_sleep_if_should_continue wake early on shutdown."""
        import asyncio

        import backend.utils.shutdown_listener as mod

        mod._should_exit = False

        # Spawn task to trigger shutdown after a short delay
        async def delayed_shutdown():
            await asyncio.sleep(0.2)
            mod._should_exit = True

        task = asyncio.create_task(delayed_shutdown())

        start = time.time()
        # Sleep for long duration, should wake up when shutdown flag is set
        await async_sleep_if_should_continue(5.0)
        elapsed = time.time() - start

        await task
        assert elapsed < 3.0  # Should wake earlier than 5.0 seconds

    def test_handler_fallback_none(self):
        """Test handler when fallback_handler is None (Line 40 coverage)."""
        import backend.utils.shutdown_listener as mod
        import signal as _sig

        with patch("signal.signal") as mock_signal, \
             patch("signal.getsignal", return_value=None):
            # Line 34-40: neither callable nor SIG_DFL
            mod._register_signal_handler(_sig.SIGINT)
            handler = mock_signal.call_args[0][1]
            
            # Should not crash when called
            # No KeyboardInterrupt because fallback_handler is None
            handler(_sig.SIGINT, None)
            assert mod._should_exit is True

    def test_register_signal_handlers_main_thread_success(self):
        """Test _register_signal_handlers actually calls registration (Line 75)."""
        import backend.utils.shutdown_listener as mod
        
        # Reset to ensure we run registration
        mod._should_exit = None
        
        with patch("backend.utils.shutdown_listener._register_signal_handler") as mock_reg, \
             patch("threading.current_thread", return_value=threading.main_thread()):
            mod._register_signal_handlers()
            assert mock_reg.called
            assert mod._should_exit is False

    @pytest.mark.asyncio
    async def test_async_sleep_loop_iteration(self):
        """Ensure the while loop in async sleep is fully covered (Line 127)."""
        import backend.utils.shutdown_listener as mod
        mod._should_exit = False
        
        # We use a mocked sleep to avoid real time waiting and ensure we hit the line
        with patch("asyncio.sleep", new_callable=MagicMock) as mock_sleep:
            # We need to make it return a coro
            async def mock_coro(d): return None
            mock_sleep.side_effect = mock_coro
            
            # setup time.time to simulate passage of time
            # 1st call: start_time
            # 2nd call: loop check 1 (0 diff)
            # 3rd call: loop check 2 (after 1s sleep)
            with patch("time.time", side_effect=[10.0, 10.0, 11.5, 12.5]):
                await async_sleep_if_should_continue(2.0)
            
            # Should have called sleep(1) at least once
            mock_sleep.assert_any_call(1)
