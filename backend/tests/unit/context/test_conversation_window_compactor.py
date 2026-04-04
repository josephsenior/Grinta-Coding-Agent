"""Tests for backend.context.compactor.strategies.conversation_window_compactor."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.context.compactor.compactor import Compaction
from backend.context.compactor.strategies.conversation_window_compactor import (
    ConversationWindowCompactor,
)
from backend.ledger.action.agent import CondensationAction, RecallAction
from backend.ledger.action.message import MessageAction, SystemMessageAction
from backend.ledger.event import EventSource
from backend.ledger.observation.empty import NullObservation

# ── Helpers ──────────────────────────────────────────────────────────


def _msg(
    eid: int, source: EventSource = EventSource.USER, content: str = 'hi'
) -> MessageAction:
    m = MessageAction(content=content, wait_for_response=False)
    m.id = eid
    m._source = source  # type: ignore[attr-defined]
    return m


def _sys_msg(eid: int) -> SystemMessageAction:
    s = SystemMessageAction(content='system prompt')
    s.id = eid
    return s


def _recall(eid: int, query: str = 'hi') -> RecallAction:
    r = RecallAction(query=query)
    r.id = eid
    return r


def _obs(eid: int, cause: int | None = None) -> NullObservation:
    o = NullObservation(content='obs')
    o.id = eid
    if cause is not None:
        o._cause = cause  # type: ignore[attr-defined]
    return o


def _view(events: list) -> MagicMock:
    v = MagicMock()
    v.events = events
    v.unhandled_condensation_request = True
    return v


# ── _find_essential_events ───────────────────────────────────────────


class TestFindEssentialEvents:
    def test_finds_system_and_first_user(self):
        cond = ConversationWindowCompactor()
        sys = _sys_msg(0)
        user = _msg(1, EventSource.USER)
        agent = _msg(2, EventSource.AGENT, content='reply')
        events = [sys, user, agent]

        sm, fm, ra, ro = cond._find_essential_events(events)
        assert sm is sys
        assert fm is user
        assert ra is None
        assert ro is None

    def test_no_system_message(self):
        cond = ConversationWindowCompactor()
        user = _msg(0, EventSource.USER)
        sm, fm, ra, ro = cond._find_essential_events([user])
        assert sm is None
        assert fm is user

    def test_no_user_message(self):
        cond = ConversationWindowCompactor()
        sys = _sys_msg(0)
        agent = _msg(1, EventSource.AGENT)
        sm, fm, ra, ro = cond._find_essential_events([sys, agent])
        assert sm is sys
        assert fm is None
        assert ra is None
        assert ro is None


# ── _build_essential_events_list ─────────────────────────────────────


class TestBuildEssentialEventsList:
    def test_all_present(self):
        cond = ConversationWindowCompactor()
        sys = _sys_msg(0)
        user = _msg(1)
        recall = _recall(2)
        obs = _obs(3, cause=2)
        result = cond._build_essential_events_list(sys, user, recall, obs)
        assert result == [0, 1, 2, 3]

    def test_system_only(self):
        cond = ConversationWindowCompactor()
        sys = _sys_msg(0)
        result = cond._build_essential_events_list(sys, None, None, None)
        assert result == [0]

    def test_none_values(self):
        cond = ConversationWindowCompactor()
        result = cond._build_essential_events_list(None, None, None, None)
        assert result == []

    def test_recall_without_observation(self):
        cond = ConversationWindowCompactor()
        recall = _recall(5)
        result = cond._build_essential_events_list(None, _msg(1), recall, None)
        assert 5 in result
        assert 1 in result


# ── _calculate_recent_events_slice ───────────────────────────────────


class TestCalculateRecentEventsSlice:
    def test_keeps_half_non_essential(self):
        cond = ConversationWindowCompactor()
        events = [_msg(i, EventSource.AGENT) for i in range(10)]
        essential = [0]  # 1 essential, 9 non-essential → keep ~4-5
        _slice, first_idx = cond._calculate_recent_events_slice(events, essential)
        assert _slice
        assert first_idx >= 0

    def test_empty_events(self):
        cond = ConversationWindowCompactor()
        _slice, first_idx = cond._calculate_recent_events_slice([], [])
        assert _slice == []


# ── _build_events_to_keep ────────────────────────────────────────────


class TestBuildEventsToKeep:
    def test_includes_essential_and_recent(self):
        cond = ConversationWindowCompactor()
        events = [_msg(i, EventSource.AGENT) for i in range(10)]
        essential = [0, 1]
        keep = cond._build_events_to_keep(events, essential, 5)
        assert 0 in keep
        assert 1 in keep
        # Events from index 5 onward should be kept
        for i in range(5, 10):
            assert events[i].id in keep


# ── _create_condensation_action ──────────────────────────────────────


class TestCreateCondensationAction:
    def test_empty_pruned(self):
        cond = ConversationWindowCompactor()
        action = cond._create_condensation_action([])
        assert isinstance(action, CondensationAction)
        assert action.pruned_event_ids == []

    def test_contiguous_range(self):
        cond = ConversationWindowCompactor()
        action = cond._create_condensation_action([2, 3, 4, 5])
        assert isinstance(action, CondensationAction)
        # Contiguous range → uses start/end IDs
        assert action.pruned_events_start_id == 2
        assert action.pruned_events_end_id == 5

    def test_non_contiguous_ids(self):
        cond = ConversationWindowCompactor()
        action = cond._create_condensation_action([1, 3, 7])
        assert isinstance(action, CondensationAction)
        assert action.pruned_event_ids == [1, 3, 7]

    def test_single_id(self):
        cond = ConversationWindowCompactor()
        action = cond._create_condensation_action([5])
        assert isinstance(action, CondensationAction)


# ── get_compaction (full pipeline) ─────────────────────────────────


class TestGetCompaction:
    def test_empty_events_returns_empty_compaction(self):
        cond = ConversationWindowCompactor()
        view = _view([])
        result = cond.get_compaction(view)
        assert isinstance(result, Compaction)
        assert result.action.pruned_event_ids == []

    def test_no_user_message_returns_empty(self):
        cond = ConversationWindowCompactor()
        view = _view([_sys_msg(0), _msg(1, EventSource.AGENT)])
        result = cond.get_compaction(view)
        assert isinstance(result, Compaction)
        assert result.action.pruned_event_ids == []

    def test_condenses_large_history(self):
        cond = ConversationWindowCompactor()
        events = [_sys_msg(0), _msg(1, EventSource.USER, 'task')]
        for i in range(2, 20):
            events.append(_msg(i, EventSource.AGENT, f'step {i}'))
        view = _view(events)
        result = cond.get_compaction(view)
        assert isinstance(result, Compaction)
        # Should prune some events but keep essential ones.
        pruned = set(result.action.pruned_event_ids or [])
        # System message and first user message should NOT be pruned.
        assert 0 not in pruned
        assert 1 not in pruned

    def test_preserves_essential_first_events(self):
        cond = ConversationWindowCompactor()
        events = [_sys_msg(0), _msg(1, EventSource.USER, 'hello')]
        for i in range(2, 30):
            src = EventSource.AGENT if i % 2 == 0 else EventSource.USER
            events.append(_msg(i, src, f'msg-{i}'))
        view = _view(events)
        result = cond.get_compaction(view)
        pruned = set(result.action.pruned_event_ids or [])
        assert 0 not in pruned
        assert 1 not in pruned


# ── should_compact ──────────────────────────────────────────────────


class TestShouldCondense:
    def test_true_when_request_pending(self):
        cond = ConversationWindowCompactor()
        view = MagicMock()
        view.unhandled_condensation_request = True
        assert cond.should_compact(view) is True

    def test_false_when_no_request(self):
        cond = ConversationWindowCompactor()
        view = MagicMock()
        view.unhandled_condensation_request = False
        assert cond.should_compact(view) is False


# ── _find_recall_and_observation ─────────────────────────────────────


class TestFindRecallAndObservation:
    def test_finds_matching_recall(self):
        cond = ConversationWindowCompactor()
        recall = _recall(5, query='find bug')
        obs = _obs(6, cause=5)
        events = [_msg(0, EventSource.USER), recall, obs]
        ra, ro = cond._find_recall_and_observation(events, 'find bug', 1)
        assert ra is recall
        assert ro is obs

    def test_no_matching_recall(self):
        cond = ConversationWindowCompactor()
        events = [_msg(0, EventSource.USER)]
        ra, ro = cond._find_recall_and_observation(events, 'nonexistent', 0)
        assert ra is None
        assert ro is None

    def test_recall_without_observation(self):
        cond = ConversationWindowCompactor()
        recall = _recall(5, query='search')
        events = [_msg(0, EventSource.USER), recall]
        ra, ro = cond._find_recall_and_observation(events, 'search', 1)
        assert ra is recall
        assert ro is None
