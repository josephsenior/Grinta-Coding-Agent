"""Unit tests for backend.core.log_shipping — LogShipper, LogShippingHandler."""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse

import pytest

from backend.core.log_shipping import LogShipper, LogShippingHandler


# ---------------------------------------------------------------------------
# LogShipper — basic queue & config
# ---------------------------------------------------------------------------


class TestLogShipper:
    def test_disabled_enqueue_is_noop(self):
        shipper = LogShipper(endpoint="http://x", enabled=False)
        shipper.enqueue({"message": "hello"})
        assert not shipper._log_queue

    def test_enabled_enqueue_adds(self):
        shipper = LogShipper(endpoint="http://x", enabled=True)
        shipper.enqueue({"message": "hello"})
        assert len(shipper._log_queue) == 1

    def test_batch_size_default(self):
        shipper = LogShipper()
        assert shipper.batch_size == 100

    def test_custom_params(self):
        shipper = LogShipper(
            batch_size=50,
            batch_timeout=10.0,
            max_retries=5,
            retry_delay=2.0,
        )
        assert shipper.batch_size == 50
        assert shipper.batch_timeout == 10.0
        assert shipper.max_retries == 5
        assert shipper.retry_delay == 2.0

    def test_dequeue_batch(self):
        shipper = LogShipper(endpoint="http://x", enabled=True, batch_size=10)
        # Directly append to queue to avoid triggering create_task
        for i in range(5):
            shipper._log_queue.append({"i": i})
        batch = shipper._dequeue_batch()
        # batch_size=10 so all 5 should be dequeued
        assert len(batch) == 5
        assert not shipper._log_queue

    def test_dequeue_batch_empty(self):
        shipper = LogShipper(endpoint="http://x", enabled=True)
        assert shipper._dequeue_batch() == []

    def test_datadog_payload(self):
        shipper = LogShipper()
        logs = [{"message": "test"}]
        payload = shipper._datadog_payload(logs)
        assert "logs" in payload
        assert len(payload["logs"]) == 1
        assert payload["logs"][0]["ddsource"] == "forge"

    async def test_flush_disabled(self):
        shipper = LogShipper(enabled=False)
        await shipper.flush()  # should not raise

    async def test_flush_empty_queue(self):
        shipper = LogShipper(endpoint="http://x", enabled=True)
        await shipper.flush()  # should not raise

    async def test_start_disabled(self):
        shipper = LogShipper(enabled=False)
        await shipper.start()
        assert shipper._ship_task is None

    async def test_stop_disabled(self):
        shipper = LogShipper(enabled=False)
        await shipper.stop()  # should not raise

    def test_build_payload_datadog(self):
        shipper = LogShipper()
        logs = [{"message": "x"}]
        parsed = urlparse("https://http-intake.logs.datadoghq.com/api/v2/logs")
        payload = shipper._build_payload(parsed, logs)
        assert "logs" in payload
        assert payload["logs"][0]["ddsource"] == "forge"

    def test_build_payload_default(self):
        shipper = LogShipper()
        logs = [{"message": "x"}]
        parsed = urlparse("https://example.com/logs")
        payload = shipper._build_payload(parsed, logs)
        assert payload == {"logs": logs}

    @pytest.mark.asyncio
    async def test_post_payload_success(self):
        shipper = LogShipper(endpoint="http://x", enabled=True)

        class FakeResponse:
            status = 200

            async def text(self):
                return "ok"

        class FakeContext:
            def __init__(self, response):
                self._response = response

            async def __aenter__(self):
                return self._response

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeSession:
            def post(self, *args, **kwargs):
                return FakeContext(FakeResponse())

        result = await shipper._post_payload(cast(Any, FakeSession()), {"logs": []}, {"X": "Y"}, 1)
        assert result is True

    @pytest.mark.asyncio
    async def test_post_payload_failure(self):
        shipper = LogShipper(endpoint="http://x", enabled=True)

        class FakeResponse:
            status = 500

            async def text(self):
                return "fail"

        class FakeContext:
            def __init__(self, response):
                self._response = response

            async def __aenter__(self):
                return self._response

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeSession:
            def post(self, *args, **kwargs):
                return FakeContext(FakeResponse())

        result = await shipper._post_payload(cast(Any, FakeSession()), {"logs": []}, {"X": "Y"}, 1)
        assert result is False

    @pytest.mark.asyncio
    async def test_ship_logs_calls_send_request(self):
        shipper = LogShipper(endpoint="http://x", enabled=True)
        logs = [{"message": "x"}]

        with patch.object(
            shipper, "_send_request", new=AsyncMock(return_value=True)
        ) as send_mock:
            result = await shipper._ship_logs(logs)

        assert result is True
        assert send_mock.called

    @pytest.mark.asyncio
    async def test_wait_for_batch_window_timeout(self, monkeypatch):
        shipper = LogShipper(endpoint="http://x", enabled=True, batch_timeout=0.01)

        async def fake_wait_for(*_args, **_kwargs):
            raise TimeoutError

        monkeypatch.setattr("backend.core.log_shipping.asyncio.wait_for", fake_wait_for)
        result = await shipper._wait_for_batch_window()
        assert result is False

    @pytest.mark.asyncio
    async def test_wait_for_batch_window_shutdown(self):
        shipper = LogShipper(endpoint="http://x", enabled=True, batch_timeout=0.01)
        shipper._shutdown_event.set()
        result = await shipper._wait_for_batch_window()
        assert result is True

    @pytest.mark.asyncio
    async def test_ship_batch_breaks_on_shutdown(self):
        shipper = LogShipper(endpoint="http://x", enabled=True)
        cast(Any, shipper)._wait_for_batch_window = AsyncMock(return_value=True)
        cast(Any, shipper)._ship_available_logs = AsyncMock()

        await shipper._ship_batch()

        cast(Any, shipper)._ship_available_logs.assert_not_called()

    @pytest.mark.asyncio
    async def test_ship_batch_runs_available_logs(self):
        shipper = LogShipper(endpoint="http://x", enabled=True)
        cast(Any, shipper)._wait_for_batch_window = AsyncMock(side_effect=[False, True])
        cast(Any, shipper)._ship_available_logs = AsyncMock()

        await shipper._ship_batch()

        cast(Any, shipper)._ship_available_logs.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_attempt_ship_with_retries(self):
        shipper = LogShipper(
            endpoint="http://x", enabled=True, max_retries=3, retry_delay=0.01
        )
        logs = [{"message": "x"}]

        cast(Any, shipper)._ship_logs = AsyncMock(side_effect=[False, True])
        with patch(
            "backend.core.log_shipping.asyncio.sleep", new=AsyncMock()
        ) as sleep_mock:
            result = await shipper._attempt_ship_with_retries(logs)

        assert result is True
        assert sleep_mock.await_count == 1

    @pytest.mark.asyncio
    async def test_ship_available_logs_failure(self):
        shipper = LogShipper(endpoint="http://x", enabled=True)
        shipper._log_queue.append({"message": "x"})

        cast(Any, shipper)._attempt_ship_with_retries = AsyncMock(return_value=False)
        await shipper._ship_available_logs()

        cast(Any, shipper)._attempt_ship_with_retries.assert_awaited_once()

    def test_enqueue_triggers_background_task(self, monkeypatch):
        shipper = LogShipper(endpoint="http://x", enabled=True, batch_size=1)

        def fake_create_task(coro):
            coro.close()
            return MagicMock()

        monkeypatch.setattr(
            "backend.core.log_shipping.asyncio.create_task", fake_create_task
        )

        shipper.enqueue({"message": "x"})
        assert shipper._ship_task is not None

    @pytest.mark.asyncio
    async def test_flush_sends_logs(self):
        shipper = LogShipper(endpoint="http://x", enabled=True)
        shipper._log_queue.append({"message": "x"})

        cast(Any, shipper)._ship_logs = AsyncMock(return_value=True)
        await shipper.flush()

        cast(Any, shipper)._ship_logs.assert_awaited_once()
        assert not shipper._log_queue

    @pytest.mark.asyncio
    async def test_start_creates_task(self, monkeypatch):
        shipper = LogShipper(endpoint="http://x", enabled=True)

        def fake_create_task(coro):
            coro.close()
            return MagicMock()

        monkeypatch.setattr(
            "backend.core.log_shipping.asyncio.create_task", fake_create_task
        )

        await shipper.start()
        assert shipper._ship_task is not None

    @pytest.mark.asyncio
    async def test_stop_closes_session_and_flushes(self):
        shipper = LogShipper(endpoint="http://x", enabled=True)
        future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        future.set_result(None)
        cast(Any, shipper)._ship_task = future

        shipper._session = MagicMock()
        shipper._session.closed = False
        shipper._session.close = AsyncMock()

        cast(Any, shipper)._ship_logs = AsyncMock(return_value=True)
        shipper._log_queue.append({"message": "x"})

        await shipper.stop()
        shipper._session.close.assert_awaited_once()

    def test_get_log_shipper_configured(self, monkeypatch):
        monkeypatch.setenv("LOG_SHIPPING_ENDPOINT", "http://x")
        monkeypatch.setenv("LOG_SHIPPING_API_KEY", "abc")
        monkeypatch.setenv("LOG_SHIPPING_ENABLED", "true")

        import backend.core.log_shipping as log_shipping

        log_shipping._log_shipper = None
        shipper = log_shipping.get_log_shipper()
        assert shipper is not None
        assert shipper.enabled is True

    def test_get_log_shipper_disabled(self, monkeypatch):
        monkeypatch.delenv("LOG_SHIPPING_ENDPOINT", raising=False)
        monkeypatch.setenv("LOG_SHIPPING_ENABLED", "false")

        import backend.core.log_shipping as log_shipping

        log_shipping._log_shipper = None
        shipper = log_shipping.get_log_shipper()
        assert shipper is None


# ---------------------------------------------------------------------------
# LogShippingHandler
# ---------------------------------------------------------------------------


class TestLogShippingHandler:
    def test_no_shipper(self):
        handler = LogShippingHandler(shipper=None)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        handler.emit(record)  # should not raise

    def test_disabled_shipper(self):
        shipper = LogShipper(enabled=False)
        handler = LogShippingHandler(shipper=shipper)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        handler.emit(record)  # should not raise, not enqueued
        assert not shipper._log_queue

    def test_enabled_shipper_enqueues(self):
        shipper = LogShipper(endpoint="http://x", enabled=True)
        handler = LogShippingHandler(shipper=shipper)
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="/p",
            lineno=42,
            msg="warn msg",
            args=(),
            exc_info=None,
        )
        handler.emit(record)
        assert len(shipper._log_queue) == 1
        entry = shipper._log_queue[0]
        assert entry["level"] == "WARNING"
        assert entry["message"] == "warn msg"
        assert entry["line"] == 42

    def test_exception_in_emit_does_not_raise(self):
        """Even if enqueue fails, the handler should not propagate."""
        shipper = MagicMock()
        shipper.enabled = True
        shipper.enqueue.side_effect = RuntimeError("fail")
        handler = LogShippingHandler(shipper=shipper)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="x",
            args=(),
            exc_info=None,
        )
        handler.emit(record)  # should not raise

    def test_emit_includes_extra_fields_and_exception(self):
        shipper = MagicMock()
        shipper.enabled = True
        handler = LogShippingHandler(shipper=shipper)
        exc_info = None

        try:
            raise ValueError("boom")
        except ValueError:
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="/p",
            lineno=5,
            msg="err",
            args=(),
            exc_info=exc_info,
        )
        record.custom_field = "custom"

        handler.emit(record)

        args, _ = shipper.enqueue.call_args
        entry = args[0]
        assert entry["custom_field"] == "custom"
        assert "exception" in entry
