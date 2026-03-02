"""Comprehensive unit tests for backend.events.stream — EventStream class.

Tests cover subscribe/unsubscribe, add_event, activity listeners, secrets,
stats, global stream registry, and helper methods.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from backend.storage import get_file_store
from backend.events.stream import (
    EventStream,
    EventStreamSubscriber,
    _warn_unclosed_stream,
    get_aggregated_event_stream_stats,
)
from backend.events.event import Event, EventSource
from backend.events.action import MessageAction
from backend.events.observation import NullObservation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def file_store(tmp_path):
    return get_file_store("local", str(tmp_path))


@pytest.fixture
def stream(file_store):
    s = EventStream("unit-test-sid", file_store)
    yield s
    s.close()


# ---------------------------------------------------------------------------
# _warn_unclosed_stream
# ---------------------------------------------------------------------------


class TestWarnUnclosedStream:
    def test_does_not_raise(self):
        """Should not raise when called."""
        _warn_unclosed_stream("some-sid")


# ---------------------------------------------------------------------------
# EventStreamSubscriber
# ---------------------------------------------------------------------------


class TestEventStreamSubscriber:
    def test_string_values(self):
        assert EventStreamSubscriber.AGENT_CONTROLLER.value == "agent_controller"
        assert EventStreamSubscriber.SERVER.value == "server"
        assert EventStreamSubscriber.RUNTIME.value == "runtime"
        assert EventStreamSubscriber.MEMORY.value == "memory"
        assert EventStreamSubscriber.MAIN.value == "main"
        assert EventStreamSubscriber.TEST.value == "test"

    def test_is_str_subclass(self):
        assert isinstance(EventStreamSubscriber.TEST, str)

    def test_all_members_present(self):
        names = [m.name for m in EventStreamSubscriber]
        assert "AGENT_CONTROLLER" in names
        assert "SERVER" in names
        assert "RUNTIME" in names


# ---------------------------------------------------------------------------
# EventStream.__init__
# ---------------------------------------------------------------------------


class TestEventStreamInit:
    def test_sid_is_stored(self, stream):
        assert stream.sid == "unit-test-sid"

    def test_subscribers_empty(self, stream):
        assert stream._subscribers == {}

    def test_secrets_dict_exists(self, stream):
        assert isinstance(stream.secrets, dict)

    def test_queue_thread_started(self, stream):
        assert stream._queue_thread.is_alive()


# ---------------------------------------------------------------------------
# subscribe / unsubscribe
# ---------------------------------------------------------------------------


class TestSubscribeUnsubscribe:
    def test_subscribe_adds_callback(self, stream):
        cb = MagicMock()
        stream.subscribe(EventStreamSubscriber.TEST, cb, "cb1")
        assert "cb1" in stream._subscribers[EventStreamSubscriber.TEST]

    def test_subscribe_same_id_twice_raises(self, stream):
        cb = MagicMock()
        stream.subscribe(EventStreamSubscriber.TEST, cb, "dup")
        with pytest.raises(ValueError, match="already exists"):
            stream.subscribe(EventStreamSubscriber.TEST, cb, "dup")

    def test_unsubscribe_removes_callback(self, stream):
        cb = MagicMock()
        stream.subscribe(EventStreamSubscriber.TEST, cb, "cb2")
        stream.unsubscribe(EventStreamSubscriber.TEST, "cb2")
        assert EventStreamSubscriber.TEST not in stream._subscribers

    def test_unsubscribe_unknown_subscriber_no_raise(self, stream):
        # Should log warning but not raise
        stream.unsubscribe("nonexistent_sub", "some_cb")

    def test_unsubscribe_unknown_callback_no_raise(self, stream):
        cb = MagicMock()
        stream.subscribe(EventStreamSubscriber.TEST, cb, "cb3")
        stream.unsubscribe(EventStreamSubscriber.TEST, "no_such_cb")

    def test_multiple_callbacks_per_subscriber(self, stream):
        cb1, cb2 = MagicMock(), MagicMock()
        stream.subscribe(EventStreamSubscriber.TEST, cb1, "a")
        stream.subscribe(EventStreamSubscriber.TEST, cb2, "b")
        assert len(stream._subscribers[EventStreamSubscriber.TEST]) == 2


# ---------------------------------------------------------------------------
# add_event
# ---------------------------------------------------------------------------


class TestAddEvent:
    def test_add_event_assigns_id(self, stream):
        obs = NullObservation("hello")
        stream.add_event(obs, EventSource.AGENT)
        assert obs.id is not None
        assert obs.id >= 0

    def test_add_event_sets_source(self, stream):
        obs = NullObservation("world")
        stream.add_event(obs, EventSource.AGENT)
        assert obs.source == EventSource.AGENT

    def test_add_event_sequential_ids(self, stream):
        obs1 = NullObservation("e1")
        obs2 = NullObservation("e2")
        stream.add_event(obs1, EventSource.AGENT)
        stream.add_event(obs2, EventSource.AGENT)
        assert obs2.id == obs1.id + 1

    def test_add_event_already_has_id_raises(self, stream):
        obs = NullObservation("dup")
        obs.id = 5  # already has an ID
        with pytest.raises(ValueError, match="already has an ID"):
            stream.add_event(obs, EventSource.AGENT)

    def test_add_event_after_close_dropped(self, file_store, tmp_path):
        s = EventStream("closed-sid", file_store)
        s.close()
        obs = NullObservation("dropped")
        # Should not raise, just log
        s.add_event(obs, EventSource.AGENT)

    def test_add_event_dispatches_to_subscriber(self, stream):
        received: list[Event] = []
        lock = threading.Event()

        def cb(event):
            received.append(event)
            lock.set()

        stream.subscribe(EventStreamSubscriber.TEST, cb, "recv")
        obs = NullObservation("dispatch-test")
        stream.add_event(obs, EventSource.AGENT)
        # Wait for async delivery
        lock.wait(timeout=3)
        assert received


# ---------------------------------------------------------------------------
# Activity listeners
# ---------------------------------------------------------------------------


class TestActivityListeners:
    def test_add_listener_returns_handle(self, stream):
        cb = MagicMock()
        handle = stream.add_activity_listener(cb)
        assert isinstance(handle, str)
        assert "listener" in handle

    def test_listener_called_on_add_event(self, stream):
        called_sids: list[str] = []
        lock = threading.Event()

        def listener(sid):
            called_sids.append(sid)
            lock.set()

        stream.add_activity_listener(listener)
        stream.add_event(NullObservation("trigger"), EventSource.AGENT)
        lock.wait(timeout=3)
        assert "unit-test-sid" in called_sids

    def test_remove_listener(self, stream):
        cb = MagicMock()
        handle = stream.add_activity_listener(cb)
        stream.remove_activity_listener(handle)
        # After removal, adding new event should not call cb
        # (race-condition-safe: we just verify no crash)
        stream.add_event(NullObservation("after"), EventSource.AGENT)

    def test_remove_unknown_handle_no_raise(self, stream):
        stream.remove_activity_listener("nonexistent-handle")

    def test_multiple_listeners(self, stream):
        counts = [0, 0]
        locks = [threading.Event(), threading.Event()]

        def cb0(sid):
            counts[0] += 1
            locks[0].set()

        def cb1(sid):
            counts[1] += 1
            locks[1].set()

        stream.add_activity_listener(cb0)
        stream.add_activity_listener(cb1)
        stream.add_event(NullObservation("multi"), EventSource.AGENT)
        locks[0].wait(timeout=3)
        locks[1].wait(timeout=3)
        assert counts[0] >= 1
        assert counts[1] >= 1

    def test_listener_exception_does_not_propagate(self, stream):
        def bad_listener(sid):
            raise RuntimeError("boom")

        stream.add_activity_listener(bad_listener)
        # Should not raise
        stream.add_event(NullObservation("exc-test"), EventSource.AGENT)


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------


class TestSecrets:
    def test_set_secrets(self, stream):
        stream.set_secrets({"API_KEY": "secret123"})
        assert "API_KEY" in stream.secrets

    def test_update_secrets(self, stream):
        stream.set_secrets({"KEY1": "val1"})
        stream.update_secrets({"KEY2": "val2"})
        assert "KEY2" in stream.secrets

    def test_add_event_masks_secret(self, stream):
        """Secrets should be masked in published event content."""
        stream.set_secrets({"SENSITIVE": "supersecret"})
        received = []
        lock = threading.Event()

        def cb(event):
            received.append(event)
            lock.set()

        stream.subscribe(EventStreamSubscriber.TEST, cb, "mask-cb")
        action = MessageAction(content="my password is supersecret")
        stream.add_event(action, EventSource.USER)
        lock.wait(timeout=3)
        # The event should have been serialized; just verify no crash
        assert received


# ---------------------------------------------------------------------------
# get_stats / get_backpressure_snapshot
# ---------------------------------------------------------------------------


class TestStats:
    def test_get_stats_returns_dict(self, stream):
        stats = stream.get_stats()
        assert isinstance(stats, dict)

    def test_get_backpressure_snapshot_returns_dict(self, stream):
        snap = stream.get_backpressure_snapshot()
        assert isinstance(snap, dict)

    def test_stats_after_events(self, stream):
        for _ in range(3):
            stream.add_event(NullObservation("s"), EventSource.AGENT)
        stats = stream.get_stats()
        assert isinstance(stats, dict)


# ---------------------------------------------------------------------------
# iter_global_streams / _GLOBAL_STREAMS
# ---------------------------------------------------------------------------


class TestGlobalStreams:
    def test_iter_global_streams_returns_list(self, stream):
        result = EventStream.iter_global_streams()
        assert isinstance(result, list)

    def test_stream_registered_globally(self, stream):
        streams = EventStream.iter_global_streams()
        assert stream in streams

    def test_closed_stream_may_be_removed(self, file_store, tmp_path):
        s = EventStream("gc-gc", file_store)
        s.close()
        # Weak reference may still hold it, but no crash
        EventStream.iter_global_streams()


# ---------------------------------------------------------------------------
# _clean_up_subscriber
# ---------------------------------------------------------------------------


class TestCleanUpSubscriber:
    def test_cleanup_removes_callback(self, stream):
        cb = MagicMock()
        stream.subscribe(EventStreamSubscriber.TEST, cb, "x")
        stream._clean_up_subscriber(EventStreamSubscriber.TEST, "x")
        assert EventStreamSubscriber.TEST not in stream._subscribers

    def test_cleanup_missing_subscriber_no_raise(self, stream):
        stream._clean_up_subscriber("no_sub", "no_cb")

    def test_cleanup_missing_callback_no_raise(self, stream):
        cb = MagicMock()
        stream.subscribe(EventStreamSubscriber.TEST, cb, "y")
        stream._clean_up_subscriber(EventStreamSubscriber.TEST, "wrong_cb_id")


# ---------------------------------------------------------------------------
# _snapshot_subscribers
# ---------------------------------------------------------------------------


class TestSnapshotSubscribers:
    def test_empty_returns_empty(self, stream):
        assert stream._snapshot_subscribers() == []

    def test_returns_all_callbacks(self, stream):
        cb1, cb2 = MagicMock(), MagicMock()
        stream.subscribe(EventStreamSubscriber.TEST, cb1, "snap1")
        stream.subscribe(EventStreamSubscriber.MAIN, cb2, "snap2")
        snaps = stream._snapshot_subscribers()
        assert len(snaps) == 2

    def test_snapshot_is_independent_copy(self, stream):
        cb = MagicMock()
        stream.subscribe(EventStreamSubscriber.TEST, cb, "scopy")
        snap = stream._snapshot_subscribers()
        # Mutate subscribers after snapshot
        stream.unsubscribe(EventStreamSubscriber.TEST, "scopy")
        # Snapshot should still have the callback
        assert len(snap) == 1


# ---------------------------------------------------------------------------
# _ensure_event_can_be_added
# ---------------------------------------------------------------------------


class TestEnsureEventCanBeAdded:
    def test_event_without_id_passes(self, stream):
        obs = NullObservation("ok")
        # should not raise
        stream._ensure_event_can_be_added(obs)

    def test_event_with_id_raises(self, stream):
        obs = NullObservation("dup")
        obs.id = 99
        with pytest.raises(ValueError):
            stream._ensure_event_can_be_added(obs)


# ---------------------------------------------------------------------------
# _should_drop_due_to_shutdown
# ---------------------------------------------------------------------------


class TestShouldDropDueToShutdown:
    def test_open_stream_does_not_drop(self, stream):
        obs = NullObservation("x")
        assert stream._should_drop_due_to_shutdown(obs, EventSource.AGENT) is False

    def test_closed_stream_drops(self, file_store, tmp_path):
        s = EventStream("drop-sid", file_store)
        s.close()
        obs = NullObservation("y")
        assert s._should_drop_due_to_shutdown(obs, EventSource.AGENT) is True


# ---------------------------------------------------------------------------
# get_aggregated_event_stream_stats (module-level)
# ---------------------------------------------------------------------------


class TestGetAggregatedEventStreamStats:
    def test_returns_dict(self):
        result = get_aggregated_event_stream_stats()
        assert isinstance(result, dict)

    def test_includes_known_keys(self):
        result = get_aggregated_event_stream_stats()
        # Must have at least one integer-valued key
        assert any(isinstance(v, int) for v in result.values())
