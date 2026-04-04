"""Tests for backend.ledger.persistence — EventPersistence."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.ledger.persistence import EventPersistence

# ===================================================================
# is_critical_event class method
# ===================================================================


class TestIsCriticalEvent:
    def test_critical_action_finish(self):
        event = SimpleNamespace(action='finish', observation=None)
        assert EventPersistence.is_critical_event(event) is True

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
