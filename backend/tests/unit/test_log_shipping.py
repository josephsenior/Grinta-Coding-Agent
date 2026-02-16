"""Unit tests for backend.core.log_shipping — LogShipper, LogShippingHandler."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from backend.core.log_shipping import LogShipper, LogShippingHandler


# ---------------------------------------------------------------------------
# LogShipper — basic queue & config
# ---------------------------------------------------------------------------


class TestLogShipper:
    def test_disabled_enqueue_is_noop(self):
        shipper = LogShipper(endpoint="http://x", enabled=False)
        shipper.enqueue({"message": "hello"})
        assert len(shipper._log_queue) == 0

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
        assert len(shipper._log_queue) == 0

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


# ---------------------------------------------------------------------------
# LogShippingHandler
# ---------------------------------------------------------------------------


class TestLogShippingHandler:
    def test_no_shipper(self):
        handler = LogShippingHandler(shipper=None)
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        handler.emit(record)  # should not raise

    def test_disabled_shipper(self):
        shipper = LogShipper(enabled=False)
        handler = LogShippingHandler(shipper=shipper)
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        handler.emit(record)  # should not raise, not enqueued
        assert len(shipper._log_queue) == 0

    def test_enabled_shipper_enqueues(self):
        shipper = LogShipper(endpoint="http://x", enabled=True)
        handler = LogShippingHandler(shipper=shipper)
        record = logging.LogRecord(
            name="test", level=logging.WARNING, pathname="/p", lineno=42,
            msg="warn msg", args=(), exc_info=None,
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
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="x", args=(), exc_info=None,
        )
        handler.emit(record)  # should not raise
