"""Tests for backend.controller.services.retry_service — RetryService."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from backend.controller.services.retry_service import RetryService


def _make_context():
    """Create a mock ControllerContext."""
    ctx = MagicMock()
    controller = MagicMock()
    controller.id = "test-ctrl-id"
    controller._closed = False
    controller._pending_action = None
    controller.state = MagicMock()
    controller.event_stream = MagicMock()
    controller.circuit_breaker_service = MagicMock()
    controller.step = MagicMock()
    ctx.get_controller.return_value = controller
    return ctx


class TestRetryServiceInit:
    def test_initial_state(self):
        ctx = _make_context()
        svc = RetryService(ctx)
        assert svc.retry_count == 0
        assert svc.retry_pending is False
        assert svc._retry_queue is None
        assert svc._retry_worker_task is None


class TestRetryMetrics:
    def test_reset_retry_metrics(self):
        ctx = _make_context()
        svc = RetryService(ctx)
        svc._retry_count = 5
        svc._retry_pending = True
        svc.reset_retry_metrics()
        assert svc.retry_count == 0
        assert svc.retry_pending is False

    def test_increment_retry_count(self):
        ctx = _make_context()
        svc = RetryService(ctx)
        assert svc.increment_retry_count() == 1
        assert svc.increment_retry_count() == 2
        assert svc.retry_count == 2


class TestController:
    def test_controller_property(self):
        ctx = _make_context()
        svc = RetryService(ctx)
        ctrl = svc.controller
        assert ctrl.id == "test-ctrl-id"


class TestInitialize:
    @patch("backend.controller.services.retry_service.get_retry_queue", return_value=None)
    def test_no_queue(self, mock_get_queue):
        ctx = _make_context()
        svc = RetryService(ctx)
        svc.initialize()
        assert svc._retry_worker_task is None

    @patch("backend.controller.services.retry_service.get_retry_queue")
    def test_no_event_loop(self, mock_get_queue):
        queue = MagicMock()
        mock_get_queue.return_value = queue
        ctx = _make_context()
        svc = RetryService(ctx)
        # With no running event loop, should just warn
        svc.initialize()
        assert svc._retry_worker_task is None


class TestIsRetryBackendFailure:
    def test_connection_error(self):
        ctx = _make_context()
        svc = RetryService(ctx)
        assert svc._is_retry_backend_failure(ConnectionError("conn lost")) is True

    def test_os_error(self):
        ctx = _make_context()
        svc = RetryService(ctx)
        assert svc._is_retry_backend_failure(OSError("os err")) is True

    def test_other_error(self):
        ctx = _make_context()
        svc = RetryService(ctx)
        assert svc._is_retry_backend_failure(ValueError("bad value")) is False


class TestShutdown:
    @pytest.mark.asyncio
    async def test_no_task(self):
        ctx = _make_context()
        svc = RetryService(ctx)
        # Should do nothing when no task
        await svc.shutdown()

    @pytest.mark.asyncio
    async def test_cancels_task(self):
        ctx = _make_context()
        svc = RetryService(ctx)
        task = MagicMock()
        task.cancel = MagicMock()
        task.done = MagicMock(return_value=False)

        async def fake_await():
            raise asyncio.CancelledError

        task.__await__ = fake_await().__await__
        svc._retry_worker_task = task
        svc._task_loop = asyncio.get_running_loop()
        await svc.shutdown()
        task.cancel.assert_called_once()
        assert svc._retry_worker_task is None

    @pytest.mark.asyncio
    async def test_stop_if_idle(self):
        ctx = _make_context()
        svc = RetryService(ctx)
        await svc.stop_if_idle()  # Should not raise


class TestScheduleRetryAfterFailure:
    @pytest.mark.asyncio
    async def test_non_retryable_error_returns_false(self):
        ctx = _make_context()
        svc = RetryService(ctx)
        with patch(
            "backend.controller.services.retry_service.get_retry_queue",
            return_value=MagicMock(),
        ):
            result = await svc.schedule_retry_after_failure(ValueError("not retryable"))
        assert result is False

    @pytest.mark.asyncio
    async def test_no_queue_returns_false(self):
        ctx = _make_context()
        svc = RetryService(ctx)
        with patch(
            "backend.controller.services.retry_service.get_retry_queue",
            return_value=None,
        ):
            from backend.llm.exceptions import RateLimitError

            result = await svc.schedule_retry_after_failure(
                RateLimitError("rate limited")
            )
        assert result is False

    @pytest.mark.asyncio
    async def test_already_pending_returns_true(self):
        from backend.llm.exceptions import APIConnectionError

        ctx = _make_context()
        svc = RetryService(ctx)
        svc._retry_pending = True
        queue = MagicMock()
        with patch(
            "backend.controller.services.retry_service.get_retry_queue",
            return_value=queue,
        ):
            result = await svc.schedule_retry_after_failure(
                APIConnectionError("timeout")
            )
        assert result is True
