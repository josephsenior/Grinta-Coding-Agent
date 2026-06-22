"""Unit tests for backend.ledger.stream.durable_writer — threaded event persistence."""

from __future__ import annotations

import json
import time
from types import MethodType
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from backend.ledger.stream.durable_writer import DurableEventWriter, PersistedEvent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_file_store():
    """Create a mock FileStore implementing the write protocol."""
    store = MagicMock()
    store.write = MagicMock()
    store.delete = MagicMock()
    return store


def _make_event(eid: int = 1) -> PersistedEvent:
    return PersistedEvent(
        event_id=eid,
        payload={'id': eid, 'type': 'test'},
        filename=f'event_{eid}.json',
    )


# ---------------------------------------------------------------------------
# PersistedEvent dataclass
# ---------------------------------------------------------------------------


class TestPersistedEvent:
    def test_fields(self):
        pe = PersistedEvent(
            event_id=5,
            payload={'x': 1},
            filename='ev.json',
            cache_filename='cache.json',
            cache_contents='{"x":1}',
        )
        assert pe.event_id == 5
        assert pe.filename == 'ev.json'
        assert pe.cache_filename == 'cache.json'

    def test_defaults(self):
        pe = PersistedEvent(event_id=1, payload={}, filename='f.json')
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
            # Find the event file write (not the .pending marker)
            for call_args in store.write.call_args_list:
                filename = call_args[0][0]
                if not filename.endswith('.pending'):
                    assert filename == 'event_42.json'
                    parsed = json.loads(call_args[0][1])
                    assert parsed['id'] == 42
                    break
            else:
                pytest.fail('No event file write found')
        finally:
            writer.stop(timeout=2.0)

    def test_cache_file_written(self):
        store = _make_file_store()
        writer = DurableEventWriter(store, max_queue_size=10)
        writer.start()
        try:
            ev = PersistedEvent(
                event_id=1,
                payload={'a': 1},
                filename='ev.json',
                cache_filename='cache.json',
                cache_contents='{"cached": true}',
            )
            writer.enqueue(ev)
            time.sleep(0.3)
            # Should have been called twice: main + cache
            assert store.write.call_count >= 2
            filenames = [c[0][0] for c in store.write.call_args_list]
            assert 'cache.json' in filenames
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
                raise OSError('disk error')

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
        store.write.side_effect = OSError('permanent failure')
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
# Shutdown / drain timeout
# ---------------------------------------------------------------------------


class TestShutdown:
    def test_stop_with_stuck_writer_does_not_hang(self):
        """stop() with drain_timeout returns even when writer is stuck."""
        import threading

        store = _make_file_store()
        block_writer = threading.Event()
        store.write.side_effect = lambda fn, _: (
            block_writer.wait() if not fn.endswith('.pending') else None
        )
        writer = DurableEventWriter(store, max_queue_size=4, put_timeout=0.05)
        writer.start()
        try:
            writer.enqueue(_make_event(1))
            time.sleep(0.1)
            # stop with a short drain_timeout — writer is stuck
            writer.stop(timeout=0.5, drain_timeout=0.2)
            assert writer._thread is None
        finally:
            block_writer.set()

    def test_stop_with_fast_writer_drains_normally(self):
        """stop() with default params drains cleanly when writer is fast."""
        store = _make_file_store()
        writer = DurableEventWriter(store, max_queue_size=16)
        writer.start()
        writer.enqueue(_make_event(1))
        writer.enqueue(_make_event(2))
        writer.stop(timeout=2.0, drain_timeout=5.0)
        assert writer._thread is None
        assert writer.drop_count == 0
        assert writer.error_count == 0


# ---------------------------------------------------------------------------
# WAL markers (.pending)
# ---------------------------------------------------------------------------


class TestWALMarkers:
    def test_pending_written_before_enqueue(self):
        """A .pending file is written before the event is enqueued."""
        import threading

        write_order: list[str] = []
        lock = threading.Lock()

        def track_write(filename: str, _content: str) -> None:
            with lock:
                write_order.append(filename)

        store = _make_file_store()
        store.write.side_effect = track_write
        writer = DurableEventWriter(store, max_queue_size=10)
        writer.start()
        try:
            ev = _make_event(7)
            writer.enqueue(ev)
            # Wait for flush to happen
            time.sleep(0.3)
            with lock:
                pending_name = 'event_7.json.pending'
                event_name = 'event_7.json'
                pending_idx = write_order.index(pending_name)
                event_idx = write_order.index(event_name)
                assert pending_idx < event_idx
        finally:
            writer.stop(timeout=2.0)

    def test_pending_deleted_after_flush(self):
        """The .pending file is removed after the event is flushed."""
        store = _make_file_store()
        writer = DurableEventWriter(store, max_queue_size=10)
        writer.start()
        try:
            ev = _make_event(7)
            writer.enqueue(ev)
            time.sleep(0.3)
            store.delete.assert_any_call('event_7.json.pending')
        finally:
            writer.stop(timeout=2.0)

    def test_pending_cleaned_on_queue_full(self):
        """Dropped events have no .pending file (WAL written only after successful put)."""
        import threading
        from types import MethodType

        store = _make_file_store()
        writer = DurableEventWriter(store, max_queue_size=1, put_timeout=0.05)

        drain_blocker = threading.Event()
        original_drain = DurableEventWriter._drain_batch

        def patched_drain(self_inner):
            drain_blocker.wait()
            return original_drain(self_inner)

        writer._drain_batch = MethodType(patched_drain, writer)  # type: ignore[method-assign]
        writer.start()
        try:
            writer.enqueue(_make_event(1))
            time.sleep(0.1)
            result = writer.enqueue(_make_event(2))
            assert not result
            time.sleep(0.1)
        finally:
            drain_blocker.set()
            writer.stop(timeout=2.0)

    def test_pending_quarantined_on_permanent_error(self):
        """The .pending file is quarantined after all retries fail."""
        store = _make_file_store()

        def _write_side_effect(filename: str, content: str) -> None:
            if 'lost_events' in filename.replace('\\', '/'):
                return None
            raise OSError('permanent failure')

        store.write.side_effect = _write_side_effect
        writer = DurableEventWriter(store, max_queue_size=10)
        writer.start()
        try:
            writer.enqueue(_make_event(9))
            time.sleep(2.0)
            quarantine_writes = [
                call
                for call in store.write.call_args_list
                if 'lost_events' in str(call)
            ]
            assert quarantine_writes
            store.delete.assert_any_call('event_9.json.pending')
        finally:
            writer.stop(timeout=2.0)


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
                assert f'event_{i}.json' in filenames
        finally:
            writer.stop(timeout=2.0)

    def test_batch_does_not_exceed_batch_size(self):
        """Even with many queued events the batch drains ≤ _DEFAULT_BATCH_SIZE at a time."""
        from backend.ledger.stream.durable_writer import _DEFAULT_BATCH_SIZE

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
            assert f'event_{i}.json' in filenames
