"""Tests for backend.context.compactor.strategies.smart_compactor - SmartCompactor."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.context.compactor.compactor import Compaction
from backend.context.compactor.strategies.smart_compactor import SmartCompactor
from backend.ledger.action import MessageAction
from backend.ledger.event import Event, EventSource
from backend.ledger.observation import ErrorObservation
from backend.ledger.observation.empty import NullObservation

# ── Helpers ──────────────────────────────────────────────────────────


def _event(eid: int, cls=None, source=EventSource.AGENT, content='x') -> Event:
    e: Event
    if cls is None or cls == MessageAction:
        e = MessageAction(content=content, wait_for_response=False)
        e._source = source  # type: ignore[attr-defined]
    elif cls == ErrorObservation:
        e = ErrorObservation(content=content)
    elif cls == NullObservation:
        e = NullObservation(content=content)
    else:
        e = NullObservation(content=content)
    e.id = eid
    return e


def _view(events: list) -> MagicMock:
    v = MagicMock()
    v.__iter__ = MagicMock(return_value=iter(events))
    v.events = events
    return v


# ── SmartCondenser init ──────────────────────────────────────────────


class TestSmartCondenserInit:
    def test_init_without_llm(self):
        sc = SmartCompactor(llm=None, max_size=100, keep_first=3)
        assert sc.llm is None
        assert sc.max_size == 100
        assert sc.keep_first == 3
        assert sc.importance_threshold == 0.6
        assert sc.recency_bonus_window == 20

    def test_init_with_custom_params(self):
        sc = SmartCompactor(
            llm=None,
            max_size=50,
            keep_first=10,
            importance_threshold=0.8,
            recency_bonus_window=5,
        )
        assert sc.importance_threshold == 0.8
        assert sc.recency_bonus_window == 5


# ── _identify_essential_events ───────────────────────────────────────


class TestIdentifyEssentialEvents:
    def test_keeps_first_n_events(self):
        sc = SmartCompactor(llm=None, keep_first=3)
        events = [_event(i) for i in range(10)]
        essential = sc._identify_essential_events(events)
        assert 0 in essential
        assert 1 in essential
        assert 2 in essential

    def test_keeps_first_user_message(self):
        sc = SmartCompactor(llm=None, keep_first=0)
        events = [
            _event(0, source=EventSource.AGENT),
            _event(1, MessageAction, source=EventSource.USER, content='hello'),
            _event(2, source=EventSource.AGENT),
        ]
        essential = sc._identify_essential_events(events)
        assert 1 in essential

    def test_keeps_critical_errors(self):
        sc = SmartCompactor(llm=None, keep_first=0)
        events = [_event(i) for i in range(60)]
        # Add a critical error in the last 50
        err = ErrorObservation(content='CRITICAL: system crash detected')
        err.id = 55
        events[55] = err
        essential = sc._identify_essential_events(events)
        assert 55 in essential

    def test_ignores_non_critical_errors(self):
        sc = SmartCompactor(llm=None, keep_first=0)
        events = [_event(i) for i in range(60)]
        err = ErrorObservation(content='minor warning about formatting')
        err.id = 55
        events[55] = err
        essential = sc._identify_essential_events(events)
        assert 55 not in essential


# ── _heuristic_scoring ───────────────────────────────────────────────


class TestHeuristicScoring:
    def test_user_messages_score_high(self):
        sc = SmartCompactor(llm=None)
        user_msg = _event(0, MessageAction, EventSource.USER, 'help me')
        scores = sc._heuristic_scoring([user_msg])
        assert scores[0] == 0.9

    def test_errors_score_high(self):
        sc = SmartCompactor(llm=None)
        err = ErrorObservation(content='something broke')
        err.id = 1
        scores = sc._heuristic_scoring([err])
        assert scores[1] == 0.8

    def test_default_score(self):
        sc = SmartCompactor(llm=None)
        obs = NullObservation(content='short')
        obs.id = 2
        scores = sc._heuristic_scoring([obs])
        # Short observation defaults to 0.5
        assert scores[2] == 0.5

    def test_long_observation_scores_higher(self):
        sc = SmartCompactor(llm=None)
        obs = NullObservation(content='x' * 600)
        obs.id = 3
        scores = sc._heuristic_scoring([obs])
        assert scores[3] == 0.6


# ── _score_event_importance ──────────────────────────────────────────


class TestScoreEventImportance:
    def test_falls_back_to_heuristic_without_llm(self):
        sc = SmartCompactor(llm=None)
        events = [_event(i) for i in range(5)]
        essential: set[int] = {0}
        scores = sc._score_event_importance(events, essential)
        # Essential events should not be scored
        assert 0 not in scores
        # Non-essential should have scores
        for eid in [1, 2, 3, 4]:
            assert eid in scores

    def test_empty_non_essential(self):
        sc = SmartCompactor(llm=None)
        events = [_event(0)]
        essential: set[int] = {0}
        scores = sc._score_event_importance(events, essential)
        assert scores == {}


# ── _select_events_to_keep ───────────────────────────────────────────


class TestSelectEventsToKeep:
    def test_keeps_essential(self):
        sc = SmartCompactor(llm=None, recency_bonus_window=5, importance_threshold=0.7)
        events = [_event(i) for i in range(20)]
        essential = {0, 1}
        scores = dict.fromkeys(range(2, 20), 0.3)  # all low
        keep = sc._select_events_to_keep(events, essential, scores)
        assert 0 in keep
        assert 1 in keep

    def test_keeps_recent_events(self):
        sc = SmartCompactor(llm=None, recency_bonus_window=5, importance_threshold=0.7)
        events = [_event(i) for i in range(20)]
        essential = {0}
        scores = dict.fromkeys(range(1, 20), 0.1)  # all very low
        keep = sc._select_events_to_keep(events, essential, scores)
        # Recent events (last 5) should be kept regardless
        for i in range(15, 20):
            assert i in keep

    def test_keeps_high_importance(self):
        sc = SmartCompactor(llm=None, recency_bonus_window=3, importance_threshold=0.5)
        events = [_event(i) for i in range(20)]
        essential: set[int] = set()
        scores = dict.fromkeys(range(20), 0.2)
        scores[5] = 0.9  # This one is high importance
        keep = sc._select_events_to_keep(events, essential, scores)
        assert 5 in keep


# ── get_compaction ─────────────────────────────────────────────────


class TestGetCompaction:
    def test_small_history_returns_empty(self):
        sc = SmartCompactor(llm=None, keep_first=5)
        events = [_event(i) for i in range(3)]
        view = _view(events)
        result = sc.get_compaction(view)
        assert isinstance(result, Compaction)
        assert result.action.pruned_event_ids == []

    def test_large_history_prunes_some(self):
        sc = SmartCompactor(
            llm=None,
            max_size=50,
            keep_first=2,
            importance_threshold=0.95,
            recency_bonus_window=3,
        )
        events = [_event(i) for i in range(30)]
        # Make first one a user message
        events[0] = _event(0, MessageAction, EventSource.USER, 'do something')
        view = _view(events)
        result = sc.get_compaction(view)
        assert isinstance(result, Compaction)
        # Should keep first events + recent + high importance.
        # Should prune at least some middle events.
        pruned = result.action.pruned_event_ids or []
        # First 2 should not be pruned (keep_first).
        assert 0 not in pruned
        assert 1 not in pruned


# ── _get_event_summary ───────────────────────────────────────────────


class TestGetEventSummary:
    def test_content_attribute(self):
        sc = SmartCompactor(llm=None)
        e = _event(0, content='hello world')
        summary = sc._get_event_summary(e)
        assert 'hello world' in summary

    def test_truncates_long_content(self):
        sc = SmartCompactor(llm=None)
        e = _event(0, content='x' * 200)
        summary = sc._get_event_summary(e)
        assert len(summary) <= 100


# ── _create_scoring_prompt ───────────────────────────────────────────


class TestCreateScoringPrompt:
    def test_builds_prompt(self):
        sc = SmartCompactor(llm=None)
        events = [_event(0, content='test'), _event(1, content='data')]
        prompt = sc._create_scoring_prompt(events)
        assert 'importance' in prompt.lower()
        assert 'MessageAction' in prompt or 'NullObservation' in prompt

    def test_lists_events(self):
        sc = SmartCompactor(llm=None)
        events = [_event(i, content=f'event-{i}') for i in range(3)]
        prompt = sc._create_scoring_prompt(events)
        assert '0.' in prompt
        assert '1.' in prompt
        assert '2.' in prompt


# ── _parse_llm_scores ────────────────────────────────────────────────


class TestParseLlmScores:
    def test_raw_json_array(self):
        sc = SmartCompactor(llm=None)
        events = [_event(0), _event(1), _event(2)]
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = '[0.8, 0.3, 0.9]'
        scores = sc._parse_llm_scores(response, events)
        assert scores[0] == pytest.approx(0.8)
        assert scores[1] == pytest.approx(0.3)
        assert scores[2] == pytest.approx(0.9)

    def test_markdown_wrapped_json(self):
        sc = SmartCompactor(llm=None)
        events = [_event(0), _event(1)]
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = '```json\n[0.5, 0.7]\n```'
        scores = sc._parse_llm_scores(response, events)
        assert scores[0] == pytest.approx(0.5)
        assert scores[1] == pytest.approx(0.7)

    def test_clamps_scores(self):
        sc = SmartCompactor(llm=None)
        events = [_event(0)]
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = '[1.5]'
        scores = sc._parse_llm_scores(response, events)
        assert scores[0] == 1.0  # Clamped to max

    def test_invalid_response_falls_back(self):
        sc = SmartCompactor(llm=None)
        events = [_event(0)]
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = 'not valid json'
        scores = sc._parse_llm_scores(response, events)
        # Should fall back to heuristic scoring
        assert 0 in scores


# ── _preserve_action_observation_pairs ───────────────────────────────


class TestPreserveActionObservationPairs:
    def test_adds_observation_for_kept_action(self):
        sc = SmartCompactor(llm=None)
        action = MessageAction(content='do something', wait_for_response=False)
        action.id = 0
        obs = NullObservation(content='result')
        obs.id = 1
        obs._cause = 0  # type: ignore[attr-defined]
        events = [action, obs]

        keep = {0}  # Keep the action
        result = sc._preserve_action_observation_pairs(events, keep)
        assert 1 in result  # Observation should be added

    def test_adds_action_for_kept_observation(self):
        sc = SmartCompactor(llm=None)
        action = MessageAction(content='do something', wait_for_response=False)
        action.id = 0
        obs = NullObservation(content='result')
        obs.id = 1
        obs._cause = 0  # type: ignore[attr-defined]
        events = [action, obs]

        keep = {1}  # Keep the observation
        result = sc._preserve_action_observation_pairs(events, keep)
        assert 0 in result  # Action should be added


# ── _get_extra_config_args ───────────────────────────────────────────


class TestGetExtraConfigArgs:
    def test_defaults(self):
        config = MagicMock(spec=[])
        args = SmartCompactor._get_extra_config_args(config)
        assert args['importance_threshold'] == 0.6
        assert args['recency_bonus_window'] == 20

    def test_from_config(self):
        config = MagicMock()
        config.importance_threshold = 0.9
        config.recency_bonus_window = 10
        args = SmartCompactor._get_extra_config_args(config)
        assert args['importance_threshold'] == 0.9
        assert args['recency_bonus_window'] == 10
