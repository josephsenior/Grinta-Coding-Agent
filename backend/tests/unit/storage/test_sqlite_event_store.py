"""Comprehensive tests for SQLiteEventStore.

Tests cover:
- Basic CRUD operations
- Batch operations
- Query filtering (event_type, source, range, limit)
- Threading and concurrency
- Edge cases and error handling
- Database lifecycle management
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from backend.storage.sqlite_event_store import SQLiteEventStore


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """Provide a temporary database path."""
    return tmp_path / "events.db"


@pytest.fixture
def store(store_path: Path) -> SQLiteEventStore:
    """Provide a fresh SQLiteEventStore instance."""
    s = SQLiteEventStore(store_path)
    yield s
    s.close()


class TestInitialization:
    """Test store initialization and schema creation."""

    def test_creates_database_file(
        self, store_path: Path, store: SQLiteEventStore
    ) -> None:
        """Test that database file is created."""
        assert store_path.exists()

    def test_creates_directory_if_missing(self, tmp_path: Path) -> None:
        """Test that parent directories are created automatically."""
        db_path = tmp_path / "nested" / "dirs" / "events.db"
        store = SQLiteEventStore(db_path)
        assert db_path.exists()
        store.close()

    def test_schema_is_created(self, store_path: Path, store: SQLiteEventStore) -> None:
        """Test that schema is properly created."""
        conn = sqlite3.connect(str(store_path))
        cursor = conn.cursor()

        # Check events table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='events'"
        )
        assert cursor.fetchone() is not None

        # Check metadata table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='metadata'"
        )
        assert cursor.fetchone() is not None

        conn.close()

    def test_repr(self, store_path: Path, store: SQLiteEventStore) -> None:
        """Test string representation."""
        assert "SQLiteEventStore" in repr(store)
        # Check that the path appears in repr (using absolute path comparison)
        assert "events.db" in repr(store)
        assert "db_path" in repr(store)


class TestWriteOperations:
    """Test event writing functionality."""

    def test_write_single_event(self, store: SQLiteEventStore) -> None:
        """Test writing a single event."""
        event = {"id": 0, "action": "test", "data": "hello"}
        store.write_event(0, event)

        result = store.read_event(0)
        assert result is not None
        assert result["action"] == "test"
        assert result["data"] == "hello"

    def test_write_event_with_timestamp(self, store: SQLiteEventStore) -> None:
        """Test writing event with explicit timestamp."""
        now = time.time()
        event = {"id": 0, "action": "test", "timestamp": now}
        store.write_event(0, event)

        result = store.read_event(0)
        assert result["timestamp"] == now

    def test_write_event_with_source(self, store: SQLiteEventStore) -> None:
        """Test writing event with source."""
        event = {"id": 0, "action": "test", "source": "agent"}
        store.write_event(0, event)

        result = store.read_event(0)
        assert result["source"] == "agent"

    def test_write_event_defaults_to_action(self, store: SQLiteEventStore) -> None:
        """Test that event_type defaults to 'action' field."""
        event = {"id": 0, "action": "my_action"}
        store.write_event(0, event)

        conn = sqlite3.connect(str(store._db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT event_type FROM events WHERE id = 0")
        event_type = cursor.fetchone()[0]
        conn.close()

        assert event_type == "my_action"

    def test_write_event_defaults_to_observation(self, store: SQLiteEventStore) -> None:
        """Test that event_type defaults to 'observation' if no action."""
        event = {"id": 0, "observation": "test_obs"}
        store.write_event(0, event)

        conn = sqlite3.connect(str(store._db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT event_type FROM events WHERE id = 0")
        event_type = cursor.fetchone()[0]
        conn.close()

        assert event_type == "test_obs"

    def test_write_event_defaults_to_unknown(self, store: SQLiteEventStore) -> None:
        """Test that event_type defaults to 'unknown' if neither action nor observation."""
        event = {"id": 0}
        store.write_event(0, event)

        conn = sqlite3.connect(str(store._db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT event_type FROM events WHERE id = 0")
        event_type = cursor.fetchone()[0]
        conn.close()

        assert event_type == "unknown"

    def test_write_event_overwrites(self, store: SQLiteEventStore) -> None:
        """Test that writing same ID overwrites previous event."""
        store.write_event(0, {"id": 0, "action": "first"})
        store.write_event(0, {"id": 0, "action": "second"})

        result = store.read_event(0)
        assert result["action"] == "second"

    def test_write_event_with_complex_json(self, store: SQLiteEventStore) -> None:
        """Test writing event with complex nested structures."""
        event = {
            "id": 0,
            "action": "complex",
            "data": {
                "nested": {"deep": [1, 2, 3]},
                "unicode": "🚀 emoji test",
            },
        }
        store.write_event(0, event)

        result = store.read_event(0)
        assert result["data"]["nested"]["deep"] == [1, 2, 3]
        assert result["data"]["unicode"] == "🚀 emoji test"

    def test_write_batch_events(self, store: SQLiteEventStore) -> None:
        """Test writing multiple events in batch."""
        events = [
            (0, {"id": 0, "action": "first"}),
            (1, {"id": 1, "action": "second"}),
            (2, {"id": 2, "action": "third"}),
        ]
        store.write_events_batch(events)

        assert store.read_event(0)["action"] == "first"
        assert store.read_event(1)["action"] == "second"
        assert store.read_event(2)["action"] == "third"

    def test_write_batch_events_empty(self, store: SQLiteEventStore) -> None:
        """Test that empty batch is safe."""
        store.write_events_batch([])
        assert store.count() == 0

    def test_write_batch_with_source(self, store: SQLiteEventStore) -> None:
        """Test batch writing with source field."""
        events = [
            (0, {"id": 0, "action": "test", "source": "agent"}),
            (1, {"id": 1, "action": "test", "source": "tool"}),
        ]
        store.write_events_batch(events)

        assert store.read_event(0)["source"] == "agent"
        assert store.read_event(1)["source"] == "tool"


class TestReadOperations:
    """Test event reading functionality."""

    def test_read_nonexistent_event(self, store: SQLiteEventStore) -> None:
        """Test reading an event that doesn't exist."""
        result = store.read_event(999)
        assert result is None

    def test_read_event_after_write(self, store: SQLiteEventStore) -> None:
        """Test reading event after write."""
        event = {"id": 5, "action": "test", "value": 42}
        store.write_event(5, event)

        result = store.read_event(5)
        assert result["action"] == "test"
        assert result["value"] == 42

    def test_list_events_empty(self, store: SQLiteEventStore) -> None:
        """Test listing events when store is empty."""
        result = store.list_events()
        assert result == []

    def test_list_events_all(self, store: SQLiteEventStore) -> None:
        """Test listing all events."""
        store.write_event(0, {"id": 0, "action": "a"})
        store.write_event(1, {"id": 1, "action": "b"})
        store.write_event(2, {"id": 2, "action": "c"})

        result = store.list_events()
        assert len(result) == 3
        assert result[0]["action"] == "a"
        assert result[1]["action"] == "b"
        assert result[2]["action"] == "c"

    def test_list_events_by_start_id(self, store: SQLiteEventStore) -> None:
        """Test listing events from start_id."""
        for i in range(5):
            store.write_event(i, {"id": i, "action": f"event_{i}"})

        result = store.list_events(start_id=2)
        assert len(result) == 3
        assert result[0]["action"] == "event_2"
        assert result[1]["action"] == "event_3"
        assert result[2]["action"] == "event_4"

    def test_list_events_by_end_id(self, store: SQLiteEventStore) -> None:
        """Test listing events with end_id (exclusive)."""
        for i in range(5):
            store.write_event(i, {"id": i, "action": f"event_{i}"})

        result = store.list_events(end_id=3)
        assert len(result) == 3
        assert result[0]["action"] == "event_0"
        assert result[2]["action"] == "event_2"

    def test_list_events_by_range(self, store: SQLiteEventStore) -> None:
        """Test listing events with both start_id and end_id."""
        for i in range(10):
            store.write_event(i, {"id": i, "action": f"event_{i}"})

        result = store.list_events(start_id=2, end_id=5)
        assert len(result) == 3
        assert [r["action"] for r in result] == ["event_2", "event_3", "event_4"]

    def test_list_events_by_event_type(self, store: SQLiteEventStore) -> None:
        """Test filtering by event_type."""
        store.write_event(0, {"action": "move"})
        store.write_event(1, {"action": "attack"})
        store.write_event(2, {"action": "move"})

        result = store.list_events(event_type="move")
        assert len(result) == 2

    def test_list_events_by_source(self, store: SQLiteEventStore) -> None:
        """Test filtering by source."""
        store.write_event(0, {"action": "test", "source": "agent"})
        store.write_event(1, {"action": "test", "source": "tool"})
        store.write_event(2, {"action": "test", "source": "agent"})

        result = store.list_events(source="agent")
        assert len(result) == 2

    def test_list_events_by_limit(self, store: SQLiteEventStore) -> None:
        """Test limiting results."""
        for i in range(10):
            store.write_event(i, {"action": f"event_{i}"})

        result = store.list_events(limit=3)
        assert len(result) == 3

    def test_list_events_combined_filters(self, store: SQLiteEventStore) -> None:
        """Test combining multiple filters."""
        store.write_event(0, {"action": "click", "source": "ui"})
        store.write_event(1, {"action": "click", "source": "api"})
        store.write_event(2, {"action": "scroll", "source": "ui"})
        store.write_event(3, {"action": "click", "source": "ui"})

        result = store.list_events(event_type="click", source="ui")
        assert len(result) == 2
        assert result[0]["action"] == "click"
        assert result[0]["source"] == "ui"

    def test_list_events_ordered_by_id(self, store: SQLiteEventStore) -> None:
        """Test that results are ordered by ID."""
        store.write_event(5, {"action": "five"})
        store.write_event(1, {"action": "one"})
        store.write_event(3, {"action": "three"})
        store.write_event(2, {"action": "two"})

        result = store.list_events()
        assert [r["action"] for r in result] == ["one", "two", "three", "five"]

    def test_count_empty(self, store: SQLiteEventStore) -> None:
        """Test counting events in empty store."""
        assert store.count() == 0

    def test_count_after_writes(self, store: SQLiteEventStore) -> None:
        """Test counting events after writes."""
        for i in range(5):
            store.write_event(i, {"action": f"event_{i}"})
        assert store.count() == 5

    def test_max_id_empty(self, store: SQLiteEventStore) -> None:
        """Test max_id on empty store."""
        assert store.max_id() == -1

    def test_max_id_after_writes(self, store: SQLiteEventStore) -> None:
        """Test max_id returns highest ID."""
        store.write_event(3, {"action": "three"})
        store.write_event(1, {"action": "one"})
        store.write_event(5, {"action": "five"})

        assert store.max_id() == 5

    def test_max_id_with_gap(self, store: SQLiteEventStore) -> None:
        """Test max_id when there's a gap in IDs."""
        store.write_event(0, {"action": "zero"})
        store.write_event(10, {"action": "ten"})

        assert store.max_id() == 10


class TestDeleteOperations:
    """Test event deletion functionality."""

    def test_delete_single_event(self, store: SQLiteEventStore) -> None:
        """Test deleting a single event."""
        store.write_event(0, {"action": "test"})
        store.write_event(1, {"action": "test"})

        store.delete_event(0)

        assert store.read_event(0) is None
        assert store.read_event(1) is not None
        assert store.count() == 1

    def test_delete_nonexistent_event(self, store: SQLiteEventStore) -> None:
        """Test deleting nonexistent event doesn't error."""
        store.delete_event(999)  # Should not raise
        assert store.count() == 0

    def test_delete_from(self, store: SQLiteEventStore) -> None:
        """Test deleting events from start_id onwards."""
        for i in range(10):
            store.write_event(i, {"action": f"event_{i}"})

        deleted = store.delete_from(5)

        assert deleted == 5
        assert store.count() == 5
        assert store.read_event(4) is not None
        assert store.read_event(5) is None
        assert store.read_event(9) is None

    def test_delete_from_returns_count(self, store: SQLiteEventStore) -> None:
        """Test delete_from returns number of deleted rows."""
        for i in range(3):
            store.write_event(i, {"action": f"event_{i}"})

        deleted = store.delete_from(1)
        assert deleted == 2

    def test_delete_from_empty_range(self, store: SQLiteEventStore) -> None:
        """Test delete_from on range with no events."""
        store.write_event(0, {"action": "test"})
        deleted = store.delete_from(10)
        assert deleted == 0


class TestConcurrency:
    """Test thread safety and concurrent access."""

    def test_concurrent_writes(self, store: SQLiteEventStore) -> None:
        """Test writing from multiple threads."""

        def write_events(start_id: int, count: int) -> None:
            for i in range(count):
                store.write_event(
                    start_id + i, {"id": start_id + i, "thread_id": start_id}
                )

        threads = [
            threading.Thread(target=write_events, args=(0, 50)),
            threading.Thread(target=write_events, args=(50, 50)),
            threading.Thread(target=write_events, args=(100, 50)),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert store.count() == 150

    def test_concurrent_reads_and_writes(self, store: SQLiteEventStore) -> None:
        """Test reading and writing concurrently."""
        results: list[Any] = []

        def writer() -> None:
            for i in range(50):
                store.write_event(i, {"id": i, "action": f"event_{i}"})
                time.sleep(0.001)

        def reader() -> None:
            for _ in range(100):
                events = store.list_events()
                results.append(len(events))
                time.sleep(0.001)

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)

        t2.start()  # Start reader first
        t1.start()

        t1.join()
        t2.join()

        # Reader should see increasing counts (not strict, just sanity check)
        assert store.count() == 50
        assert all(0 <= count <= 50 for count in results)

    def test_batch_write_is_atomic(self, store: SQLiteEventStore) -> None:
        """Test that batch write is atomic."""
        events = [(i, {"id": i, "action": f"event_{i}"}) for i in range(100)]
        store.write_events_batch(events)

        assert store.count() == 100
        assert store.max_id() == 99


class TestDataIntegrity:
    """Test data integrity and edge cases."""

    def test_special_characters_preserved(self, store: SQLiteEventStore) -> None:
        """Test that special characters are preserved."""
        special = "!@#$%^&*(){}[]|\\:;\"'<>?,./\n\t€©®™"
        store.write_event(0, {"text": special})

        result = store.read_event(0)
        assert result["text"] == special

    def test_very_large_payload(self, store: SQLiteEventStore) -> None:
        """Test writing and reading very large payloads."""
        large_data = "x" * 10000
        store.write_event(0, {"data": large_data})

        result = store.read_event(0)
        assert result["data"] == large_data
        assert len(result["data"]) == 10000

    def test_numeric_values_preserved(self, store: SQLiteEventStore) -> None:
        """Test that numeric types are preserved through JSON."""
        store.write_event(
            0,
            {
                "int": 42,
                "float": 3.14159,
                "negative": -100,
                "zero": 0,
            },
        )

        result = store.read_event(0)
        assert result["int"] == 42
        assert result["float"] == 3.14159
        assert result["negative"] == -100
        assert result["zero"] == 0

    def test_null_values_handled(self, store: SQLiteEventStore) -> None:
        """Test that null values are handled correctly."""
        store.write_event(0, {"nullable": None, "exists": "value"})

        result = store.read_event(0)
        assert result["nullable"] is None
        assert result["exists"] == "value"

    def test_boolean_values_preserved(self, store: SQLiteEventStore) -> None:
        """Test that booleans are preserved."""
        store.write_event(0, {"yes": True, "no": False})

        result = store.read_event(0)
        assert result["yes"] is True
        assert result["no"] is False

    def test_list_values_preserved(self, store: SQLiteEventStore) -> None:
        """Test that lists are preserved."""
        store.write_event(0, {"items": [1, "two", 3.0, None, True]})

        result = store.read_event(0)
        assert result["items"] == [1, "two", 3.0, None, True]


class TestLifecycle:
    """Test connection lifecycle management."""

    def test_close_closes_connection(self, store_path: Path) -> None:
        """Test that close() properly closes the connection."""
        store = SQLiteEventStore(store_path)
        store.write_event(0, {"action": "test"})
        store.close()

        # Connection should be None after close
        assert store._conn is None

    def test_store_is_reusable_after_init(self, store_path: Path) -> None:
        """Test that the same database can be reopened."""
        store1 = SQLiteEventStore(store_path)
        store1.write_event(0, {"action": "first"})
        store1.close()

        # Reopen the same database
        store2 = SQLiteEventStore(store_path)
        result = store2.read_event(0)
        assert result is not None
        assert result["action"] == "first"
        store2.close()

    def test_multiple_operations_after_close_and_reopen(self, store_path: Path) -> None:
        """Test that store works correctly after close/reopen cycles."""
        store = SQLiteEventStore(store_path)
        store.write_event(0, {"action": "first"})
        store.close()

        store = SQLiteEventStore(store_path)
        store.write_event(1, {"action": "second"})
        events = store.list_events()

        assert len(events) == 2
        store.close()


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_write_event_with_none_source(self, store: SQLiteEventStore) -> None:
        """Test that None source is handled gracefully."""
        store.write_event(0, {"action": "test", "source": None})
        result = store.read_event(0)
        assert result["source"] is None

    def test_list_events_with_nonexistent_source(self, store: SQLiteEventStore) -> None:
        """Test filtering by source that doesn't exist."""
        store.write_event(0, {"action": "test", "source": "exists"})
        result = store.list_events(source="nonexistent")
        assert result == []

    def test_list_events_with_nonexistent_event_type(
        self, store: SQLiteEventStore
    ) -> None:
        """Test filtering by event_type that doesn't exist."""
        store.write_event(0, {"action": "real"})
        result = store.list_events(event_type="fake")
        assert result == []
