"""Tests for backend.utils.shutdown_listener — shutdown coordination (no signals)."""

import asyncio
import time
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from backend.utils.shutdown_listener import (
    add_shutdown_listener,
    async_sleep_if_should_continue,
    remove_shutdown_listener,
    request_process_shutdown,
    reset_shutdown_state,
    should_continue,
    should_exit,
    sleep_if_should_continue,
)


@pytest.fixture(autouse=True)
def reset_shutdown_listener():
    """Reset shutdown listener state between tests."""
    import backend.utils.shutdown_listener as mod

    mod._should_exit = False
    mod._shutdown_listeners.clear()
    yield
    mod._should_exit = False
    mod._shutdown_listeners.clear()


class TestShouldExit:
    def test_returns_bool(self):
        assert isinstance(should_exit(), bool)

    def test_initially_false(self):
        assert should_exit() is False


class TestShouldContinue:
    def test_returns_bool(self):
        assert isinstance(should_continue(), bool)

    def test_initially_true(self):
        assert should_continue() is True

    def test_opposite_of_should_exit(self):
        import backend.utils.shutdown_listener as mod

        mod._should_exit = False
        assert should_continue() is True
        assert should_exit() is False


class TestResetShutdownState:
    def test_resets_stale_exit_flag(self):
        import backend.utils.shutdown_listener as mod

        mod._should_exit = True
        reset_shutdown_state()
        assert mod._should_exit is False


class TestSleepIfShouldContinue:
    def test_sleeps_short_duration(self):
        start = time.time()
        sleep_if_should_continue(0.1)
        elapsed = time.time() - start
        assert 0.08 <= elapsed <= 0.2

    def test_sleeps_long_duration_in_chunks(self):
        import backend.utils.shutdown_listener as mod

        mod._should_exit = False
        start = time.time()
        sleep_if_should_continue(0.5)
        elapsed = time.time() - start
        assert elapsed >= 0.4


@pytest.mark.asyncio
class TestAsyncSleepIfShouldContinue:
    async def test_async_sleeps_short(self):
        start = time.time()
        await async_sleep_if_should_continue(0.1)
        elapsed = time.time() - start
        assert 0.08 <= elapsed <= 0.25

    async def test_async_sleeps_long(self):
        import backend.utils.shutdown_listener as mod

        mod._should_exit = False
        start = time.time()
        await async_sleep_if_should_continue(0.5)
        elapsed = time.time() - start
        assert elapsed >= 0.4


class TestAddShutdownListener:
    def test_returns_uuid(self):
        listener = MagicMock()
        listener_id = add_shutdown_listener(listener)
        assert isinstance(listener_id, UUID)

    def test_listener_added_to_dict(self):
        import backend.utils.shutdown_listener as mod

        initial_count = len(mod._shutdown_listeners)
        listener = MagicMock()
        listener_id = add_shutdown_listener(listener)
        assert len(mod._shutdown_listeners) == initial_count + 1
        assert mod._shutdown_listeners[listener_id] == listener

    def test_multiple_listeners_have_unique_ids(self):
        id1 = add_shutdown_listener(MagicMock())
        id2 = add_shutdown_listener(MagicMock())
        assert id1 != id2


class TestRemoveShutdownListener:
    def test_removes_existing_listener(self):
        listener_id = add_shutdown_listener(MagicMock())
        assert remove_shutdown_listener(listener_id) is True

    def test_returns_false_for_nonexistent_listener(self):
        from uuid import uuid4

        assert remove_shutdown_listener(uuid4()) is False

    def test_listener_removed_from_dict(self):
        import backend.utils.shutdown_listener as mod

        listener_id = add_shutdown_listener(MagicMock())
        assert listener_id in mod._shutdown_listeners
        remove_shutdown_listener(listener_id)
        assert listener_id not in mod._shutdown_listeners


class TestRequestProcessShutdown:
    def test_sets_exit_flag(self):
        import backend.utils.shutdown_listener as mod

        assert mod._should_exit is False
        request_process_shutdown()
        assert mod._should_exit is True

    def test_idempotent(self):
        import backend.utils.shutdown_listener as mod

        request_process_shutdown()
        request_process_shutdown()
        assert mod._should_exit is True

    def test_invokes_listeners_once(self):
        listener1 = MagicMock()
        listener2 = MagicMock()
        add_shutdown_listener(listener1)
        add_shutdown_listener(listener2)
        request_process_shutdown()
        listener1.assert_called_once()
        listener2.assert_called_once()
        listener1.reset_mock()
        listener2.reset_mock()
        request_process_shutdown()
        listener1.assert_not_called()
        listener2.assert_not_called()

    def test_listener_exceptions_do_not_block_others(self):
        failing = MagicMock(side_effect=RuntimeError("listener error"))
        successful = MagicMock()
        add_shutdown_listener(failing)
        add_shutdown_listener(successful)
        request_process_shutdown()
        failing.assert_called_once()
        successful.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_sleep_wake_early(self):
        import backend.utils.shutdown_listener as mod

        mod._should_exit = False

        async def delayed_shutdown():
            await asyncio.sleep(0.2)
            request_process_shutdown()

        task = asyncio.create_task(delayed_shutdown())
        start = time.time()
        await async_sleep_if_should_continue(5.0)
        elapsed = time.time() - start
        await task
        assert elapsed < 3.0


class TestShutdownListenerEdgeCases:
    def test_sleep_long_duration_chunks(self):
        import backend.utils.shutdown_listener as mod

        mod._should_exit = False
        start = time.time()
        sleep_if_should_continue(1.2)
        assert time.time() - start >= 1.0

    @pytest.mark.asyncio
    async def test_async_sleep_long_duration_chunks(self):
        import backend.utils.shutdown_listener as mod

        mod._should_exit = False
        start = time.time()
        await async_sleep_if_should_continue(1.2)
        assert time.time() - start >= 1.0

    @pytest.mark.asyncio
    async def test_async_sleep_loop_iteration(self):
        import backend.utils.shutdown_listener as mod

        mod._should_exit = False
        with patch("asyncio.sleep", new_callable=MagicMock) as mock_sleep:

            async def mock_coro(_d):
                return None

            mock_sleep.side_effect = mock_coro
            with patch("time.time", side_effect=[10.0, 10.0, 11.5, 12.5]):
                await async_sleep_if_should_continue(2.0)
            mock_sleep.assert_any_call(1)
