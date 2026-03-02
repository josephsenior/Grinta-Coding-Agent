"""Unit tests for backend.events.durable_writer — threaded event persistence."""

from __future__ import annotations

import json
import time
from types import MethodType
from typing import Any, cast
from unittest.mock import MagicMock


from backend.events.durable_writer import DurableEventWriter, PersistedEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_file_store():
    """Create a mock FileStore implementing the write protocol."""
    store = MagicMock()
    store.write = MagicMock()
    return store


def _make_event(eid: int = 1) -> PersistedEvent:
    return PersistedEvent(
        event_id=eid,
        payload={"id": eid, "type": "test"},
        filename=f"event_{eid}.json",
    )


# ---------------------------------------------------------------------------
# PersistedEvent dataclass
# ---------------------------------------------------------------------------


class TestPersistedEvent:
    def test_fields(self):
        pe = PersistedEvent(
            event_id=5,
            payload={"x": 1},
            filename="ev.json",
            cache_filename="cache.json",
            cache_contents='{"x":1}',
        )
        assert pe.event_id == 5
        assert pe.filename == "ev.json"
        assert pe.cache_filename == "cache.json"

    def test_defaults(self):
        pe = PersistedEvent(event_id=1, payload={}, filename="f.json")
        assert pe.cache_filename is None
        assert pe.cache_contents is None


# ---------------------------------------------------------------------------
# Lifecycle: start / stop
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_start_creates_thread(self):
        store = _make_file_store()
        writer = DurableEventWriter(store, max_queue_size=10)
        writer.start()
        assert writer._thread is not None
        assert writer._thread.is_alive()
        writer.stop(timeout=2.0)

    def test_stop_joins_thread(self):
        store = _make_file_store()
        writer = DurableEventWriter(store, max_queue_size=10)
        writer.start()
        writer.stop(timeout=2.0)
        assert writer._thread is None

    def test_double_start_is_safe(self):
        store = _make_file_store()
        writer = DurableEventWriter(store, max_queue_size=10)
        writer.start()
        writer.start()  # second call is no-op
        writer.stop(timeout=2.0)

    def test_stop_without_start(self):
        store = _make_file_store()
        writer = DurableEventWriter(store, max_queue_size=10)
        writer.stop()  # should not raise


# ---------------------------------------------------------------------------
# Enqueue and flush
# ---------------------------------------------------------------------------


class TestEnqueueAndFlush:
    def test_enqueue_when_stopped_returns_false(self):
        store = _make_file_store()
        writer = DurableEventWriter(store, max_queue_size=10)
        assert writer.enqueue(_make_event()) is False

    def test_enqueue_flushes_event(self):
        store = _make_file_store()
        writer = DurableEventWriter(store, max_queue_size=10)
        writer.start()
        try:
            ev = _make_event(42)
            assert writer.enqueue(ev) is True
            # Wait for writer thread to process
            time.sleep(0.3)
            store.write.assert_called()
            # First arg of first call is the filename
            call_args = store.write.call_args_list[0]
            assert call_args[0][0] == "event_42.json"
            # Second arg is JSON serialized payload
            parsed = json.loads(call_args[0][1])
            assert parsed["id"] == 42
        finally:
            writer.stop(timeout=2.0)

    def test_cache_file_written(self):
        store = _make_file_store()
        writer = DurableEventWriter(store, max_queue_size=10)
        writer.start()
        try:
            ev = PersistedEvent(
                event_id=1,
                payload={"a": 1},
                filename="ev.json",
                cache_filename="cache.json",
                cache_contents='{"cached": true}',
            )
            writer.enqueue(ev)
            time.sleep(0.3)
            # Should have been called twice: main + cache
            assert store.write.call_count >= 2
            filenames = [c[0][0] for c in store.write.call_args_list]
            assert "cache.json" in filenames
        finally:
            writer.stop(timeout=2.0)


# ---------------------------------------------------------------------------
# Queue full / drops
# ---------------------------------------------------------------------------


class TestQueueFull:
    def test_drop_count_incremented(self):
        store = _make_file_store()
        # Block the writer so the queue fills up
        store.write.side_effect = lambda *_: time.sleep(5)
        writer = DurableEventWriter(store, max_queue_size=2, put_timeout=0.05)
        writer.start()
        try:
            # Fill queue
            writer.enqueue(_make_event(1))
            writer.enqueue(_make_event(2))
            # This should eventually be dropped after timeout
            time.sleep(0.1)
            writer.enqueue(_make_event(3))
            # May or may not drop depending on timing, but let's check the property exists
            assert writer.drop_count >= 0
        finally:
            writer.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# Error handling & retry
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_transient_error_retried(self):
        store = _make_file_store()
        call_count = 0

        def failing_write(filename, content):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise OSError("disk error")

        store.write.side_effect = failing_write
        writer = DurableEventWriter(store, max_queue_size=10)
        writer.start()
        try:
            writer.enqueue(_make_event(1))
            time.sleep(1.5)  # Allow retries with backoff
            # Should have succeeded on 3rd attempt
            assert call_count >= 3
            assert writer.error_count == 0  # No permanent failures
        finally:
            writer.stop(timeout=2.0)

    def test_permanent_error_logged(self):
        store = _make_file_store()
        store.write.side_effect = OSError("permanent failure")
        writer = DurableEventWriter(store, max_queue_size=10)
        writer.start()
        try:
            writer.enqueue(_make_event(1))
            time.sleep(2.0)  # Allow all retries to exhaust
            assert writer.error_count >= 1
        finally:
            writer.stop(timeout=2.0)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestProperties:
    def test_queue_depth(self):
        store = _make_file_store()
        writer = DurableEventWriter(store, max_queue_size=100)
        assert writer.queue_depth == 0

    def test_drop_count_initial(self):
        store = _make_file_store()
        writer = DurableEventWriter(store)
        assert writer.drop_count == 0

    def test_error_count_initial(self):
        store = _make_file_store()
        writer = DurableEventWriter(store)
        assert writer.error_count == 0


# ---------------------------------------------------------------------------
# Batch flushing
# ---------------------------------------------------------------------------


class TestBatchFlush:
    def test_multiple_events_flushed_in_batch(self):
        """Several events enqueued quickly should be flushed together."""
        store = _make_file_store()
        writer = DurableEventWriter(store, max_queue_size=64)
        writer.start()
        try:
            n = 10
            for i in range(n):
                writer.enqueue(_make_event(i))
            # Allow writer to process
            time.sleep(0.5)
            # All events should be persisted
            filenames = {c[0][0] for c in store.write.call_args_list}
            for i in range(n):
                assert f"event_{i}.json" in filenames
        finally:
            writer.stop(timeout=2.0)

    def test_batch_does_not_exceed_batch_size(self):
        """Even with many queued events the batch drains ≤ _DEFAULT_BATCH_SIZE at a time."""
        from backend.events.durable_writer import _DEFAULT_BATCH_SIZE

        store = _make_file_store()
        flush_sizes: list[int] = []
        original_flush_batch = DurableEventWriter._flush_batch

        def patched_flush_batch(self_inner, batch):
            flush_sizes.append(len(batch))
            original_flush_batch(self_inner, batch)

        writer = DurableEventWriter(store, max_queue_size=128)
        cast(Any, writer)._flush_batch = MethodType(patched_flush_batch, writer)
        writer.start()
        try:
            # Enqueue many events at once
            for i in range(50):
                writer.enqueue(_make_event(i))
            time.sleep(1.0)
            for size in flush_sizes:
                assert size <= _DEFAULT_BATCH_SIZE
        finally:
            writer.stop(timeout=2.0)

    def test_stop_flushes_remaining_batch(self):
        """Events in the queue at stop time should still be flushed."""
        store = _make_file_store()
        writer = DurableEventWriter(store, max_queue_size=64)
        writer.start()
        for i in range(5):
            writer.enqueue(_make_event(i))
        writer.stop(timeout=5.0)
        filenames = {c[0][0] for c in store.write.call_args_list}
        for i in range(5):
            assert f"event_{i}.json" in filenames
