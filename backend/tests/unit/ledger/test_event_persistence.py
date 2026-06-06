"""Tests for backend.ledger.persistence — EventPersistence."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.ledger.persistence import EventPersistence

# ===================================================================
# is_critical_event class method
# ===================================================================


class TestIsCriticalEvent:
    def test_legacy_finish_action_not_critical(self):
        """The 'finish' action type was removed; no longer a critical event."""
        event = SimpleNamespace(action='finish', observation=None)
        assert EventPersistence.is_critical_event(event) is False

    def test_critical_action_reject(self):
        event = SimpleNamespace(action='reject', observation=None)
        assert EventPersistence.is_critical_event(event) is True

    def test_critical_action_change_agent_state(self):
        event = SimpleNamespace(action='change_agent_state', observation=None)
        assert EventPersistence.is_critical_event(event) is True

    def test_critical_observation_error(self):
        event = SimpleNamespace(action=None, observation='error')
        assert EventPersistence.is_critical_event(event) is True

    def test_critical_observation_agent_state_changed(self):
        event = SimpleNamespace(action=None, observation='agent_state_changed')
        assert EventPersistence.is_critical_event(event) is True

    def test_critical_observation_user_rejected(self):
        event = SimpleNamespace(action=None, observation='user_rejected')
        assert EventPersistence.is_critical_event(event) is True

    def test_non_critical_action(self):
        event = SimpleNamespace(action='run', observation=None)
        assert EventPersistence.is_critical_event(event) is False

    def test_non_critical_observation(self):
        event = SimpleNamespace(action=None, observation='run')
        assert EventPersistence.is_critical_event(event) is False

    def test_no_action_no_observation(self):
        event = SimpleNamespace()
        assert EventPersistence.is_critical_event(event) is False

    def test_non_string_action(self):
        event = SimpleNamespace(action=42, observation=None)
        assert EventPersistence.is_critical_event(event) is False


# ===================================================================
# Init
# ===================================================================


class TestEventPersistenceInit:
    def test_default_stats(self):
        ep = EventPersistence(
            sid='sess-1',
            file_store=MagicMock(),
            user_id=None,
        )
        assert ep.stats['persist_failures'] == 0
        assert ep.stats['cache_write_failures'] == 0
        assert ep.stats['critical_sync_persistence'] == 0
        assert ep.stats['durable_enqueue_failures'] == 0

    def test_custom_cache_size(self):
        ep = EventPersistence(
            sid='sess-2',
            file_store=MagicMock(),
            user_id='user-1',
            cache_size=100,
        )
        assert ep._cache_size == 100

    def test_stores_sid_and_user(self):
        ep = EventPersistence(
            sid='sess-3',
            file_store=MagicMock(),
            user_id='u-42',
        )
        assert ep.sid == 'sess-3'
        assert ep.user_id == 'u-42'

    def test_initial_health_fields_none(self):
        ep = EventPersistence(sid='sess-4', file_store=MagicMock(), user_id=None)
        snap = ep.get_health_snapshot()
        assert snap['last_confirmed_event_id'] is None
        assert snap['last_confirmed_critical_event_id'] is None
        assert snap['last_enqueued_event_id'] is None


# ===================================================================
# Health tracking
# ===================================================================


class TestHealthTracking:
    def test_sqlite_write_updates_last_confirmed(self):
        """SQLite path records _last_confirmed_event_id."""
        ep = EventPersistence(sid='sess-h1', file_store=MagicMock(), user_id=None)
        ep._sqlite_store = MagicMock()
        ep._sqlite_store.write_event = MagicMock()

        ep.persist_event(
            payload={'id': 42, 'action': 'move'},
            event_id=42,
            cache_payload=None,
        )
        assert ep._last_confirmed_event_id == 42

    def test_sqlite_write_health_snapshot(self):
        """Health snapshot reflects SQLite writes."""
        ep = EventPersistence(sid='sess-h2', file_store=MagicMock(), user_id=None)
        ep._sqlite_store = MagicMock()
        ep._sqlite_store.write_event = MagicMock()

        ep.persist_event(
            payload={'id': 99, 'action': 'move'},
            event_id=99,
            cache_payload=None,
        )
        snap = ep.get_health_snapshot()
        assert snap['last_confirmed_event_id'] == 99

    def test_async_enqueue_updates_last_enqueued(self):
        """Async writer path records _last_enqueued_event_id."""
        ep = EventPersistence(
            sid='sess-h3',
            file_store=MagicMock(),
            user_id=None,
            get_filename_for_id=lambda eid, uid: f'events/{eid}.json',
        )
        ep._sqlite_store = None  # disable SQLite
        # Wire a working async writer
        writer = MagicMock()
        writer.enqueue.return_value = True
        ep._durable_writer = writer

        ep.persist_event(
            payload={'id': 77, 'action': 'read'},
            event_id=77,
            cache_payload=None,
        )
        assert ep._last_enqueued_event_id == 77

    def test_async_enqueue_health_snapshot(self):
        """Health snapshot reflects last enqueued event."""
        ep = EventPersistence(
            sid='sess-h4',
            file_store=MagicMock(),
            user_id=None,
            get_filename_for_id=lambda eid, uid: f'events/{eid}.json',
        )
        ep._sqlite_store = None
        writer = MagicMock()
        writer.enqueue.return_value = True
        ep._durable_writer = writer

        ep.persist_event(
            payload={'id': 55, 'action': 'search'},
            event_id=55,
            cache_payload=None,
        )
        snap = ep.get_health_snapshot()
        assert snap['last_enqueued_event_id'] == 55

    def test_sync_write_updates_both_confirmed(self):
        """Sync fallback path records _last_confirmed_event_id."""
        file_store = MagicMock()
        ep = EventPersistence(
            sid='sess-h5',
            file_store=file_store,
            user_id=None,
            get_filename_for_id=lambda eid, uid: f'events/{eid}.json',
        )
        ep._sqlite_store = None  # disable SQLite
        ep._durable_writer = None  # disable async

        ep.persist_event(
            payload={'id': 33, 'action': 'write'},
            event_id=33,
            cache_payload=None,
        )
        assert ep._last_confirmed_event_id == 33
