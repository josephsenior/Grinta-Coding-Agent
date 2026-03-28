"""Integration tests for EventStream durable persistence and WAL recovery."""

from __future__ import annotations

import json
import tempfile

from backend.ledger import EventSource
from backend.ledger.observation.empty import NullObservation
from backend.ledger.serialization.event import event_to_dict
from backend.ledger.stream import EventStream
from backend.persistence.local_file_store import LocalFileStore
from backend.persistence.locations import get_conversation_events_dir


def test_event_stream_replays_pending_event_on_startup() -> None:
    sid = "wal-replay-session"
    with tempfile.TemporaryDirectory() as tmpdir:
        file_store = LocalFileStore(tmpdir)
        events_dir = get_conversation_events_dir(sid)
        pending_path = f"{events_dir}0.json.pending"
        event = NullObservation(content="recovered")
        event.id = 0
        event.source = EventSource.AGENT
        payload = event_to_dict(event)
        file_store.write(pending_path, json.dumps(payload))

        stream = EventStream(sid, file_store)
        try:
            recovered = stream.get_event(0)
            assert recovered.id == 0
            assert getattr(recovered, "observation", None) == "null"
            assert stream.cur_id >= 1
        finally:
            stream.close()


def test_event_stream_cleans_stale_pending_marker() -> None:
    sid = "wal-clean-session"
    with tempfile.TemporaryDirectory() as tmpdir:
        file_store = LocalFileStore(tmpdir)
        events_dir = get_conversation_events_dir(sid)
        event_path = f"{events_dir}0.json"
        pending_path = f"{event_path}.pending"
        event = NullObservation(content="already-written")
        event.id = 0
        event.source = EventSource.AGENT
        payload = event_to_dict(event)
        file_store.write(event_path, json.dumps(payload))
        file_store.write(pending_path, json.dumps(payload))

        stream = EventStream(sid, file_store)
        try:
            listing = file_store.list(events_dir)
            assert f"{events_dir}0.json.pending" not in listing
            assert f"{events_dir}0.json" in listing
        finally:
            stream.close()


def test_event_stream_persists_and_loads_events_across_restart() -> None:
    sid = "persist-restart-session"
    with tempfile.TemporaryDirectory() as tmpdir:
        file_store = LocalFileStore(tmpdir)

        stream = EventStream(sid, file_store)
        try:
            stream.add_event(NullObservation(content="first"), EventSource.AGENT)
            stream.add_event(NullObservation(content="second"), EventSource.AGENT)
        finally:
            stream.close()

        restarted = EventStream(sid, file_store)
        try:
            events = list(restarted.search_events(start_id=0, end_id=1))
            assert len(events) == 2
            assert [event.id for event in events] == [0, 1]
            assert restarted.cur_id >= 2
        finally:
            restarted.close()

