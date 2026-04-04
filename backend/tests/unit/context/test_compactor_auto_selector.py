"""Tests for backend.context.compactor.strategies.auto_selector - task-aware compactor selection."""

from __future__ import annotations

import pytest

from backend.context.compactor.strategies.auto_selector import (
    _HIGH_ERROR_RATIO,
    _LONG_SESSION,
    _MEDIUM_SESSION,
    _SHORT_SESSION,
    TaskSignals,
    compute_signals,
    select_compactor_config,
)
from backend.core.config.compactor_config import (
    AmortizedPruningCompactorConfig,
    AutoCompactorConfig,
    NoOpCompactorConfig,
    ObservationMaskingCompactorConfig,
    RecentEventsCompactorConfig,
    SmartCompactorConfig,
)
from backend.ledger.action import CmdRunAction, MessageAction
from backend.ledger.event import Event, EventSource
from backend.ledger.observation import CmdOutputObservation, ErrorObservation

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user_message(eid: int, content: str = 'hello') -> MessageAction:
    ev = MessageAction(content=content)
    ev._source = EventSource.USER
    ev._id = eid
    return ev


def _make_cmd(eid: int, command: str = 'ls') -> CmdRunAction:
    ev = CmdRunAction(command=command)
    ev._id = eid
    return ev


def _make_error(eid: int, content: str = 'error occurred') -> ErrorObservation:
    ev = ErrorObservation(content=content)
    ev._id = eid
    return ev


def _make_cmd_output(eid: int, content: str = 'output') -> CmdOutputObservation:
    ev = CmdOutputObservation(content=content, command_id=0, command='ls')
    ev._id = eid
    return ev


def _make_events(n: int) -> list[Event]:
    """Create n generic command events."""
    events: list[Event] = []
    for i in range(n):
        events.append(_make_cmd(i, f'cmd_{i}'))
    return events


def _make_error_heavy_events(total: int, error_count: int) -> list[Event]:
    """Create events where error_count are errors and rest are commands."""
    events: list[Event] = []
    for i in range(total):
        if i < error_count:
            events.append(_make_error(i, f'error_{i}'))
        else:
            events.append(_make_cmd(i, f'cmd_{i}'))
    return events


# ---------------------------------------------------------------------------
# TaskSignals
# ---------------------------------------------------------------------------


class TestTaskSignals:
    def test_defaults(self):
        sig = TaskSignals()
        assert sig.total_events == 0
        assert sig.error_count == 0
        assert sig.error_ratio == 0.0

    def test_slots(self):
        """TaskSignals should be a slot class."""
        assert hasattr(TaskSignals, '__slots__')


# ---------------------------------------------------------------------------
# compute_signals
# ---------------------------------------------------------------------------


class TestComputeSignals:
    def test_empty_events(self):
        sig = compute_signals([])
        assert sig.total_events == 0
        assert sig.error_ratio == 0.0

    def test_counts_errors(self):
        events = [_make_error(1), _make_error(2), _make_cmd(3)]
        sig = compute_signals(events)
        assert sig.error_count == 2
        assert sig.total_events == 3
        assert sig.error_ratio == pytest.approx(2 / 3)

    def test_counts_user_messages(self):
        events = [_make_user_message(1), _make_user_message(2), _make_cmd(3)]
        sig = compute_signals(events)
        assert sig.user_message_count == 2

    def test_counts_commands(self):
        events = [_make_cmd(1), _make_cmd(2)]
        sig = compute_signals(events)
        assert sig.cmd_run_count == 2

    def test_avg_observation_length(self):
        events = [
            _make_cmd_output(1, 'short'),
            _make_cmd_output(2, 'a' * 100),
        ]
        sig = compute_signals(events)
        assert sig.avg_observation_length == pytest.approx((5 + 100) / 2)


# ---------------------------------------------------------------------------
# select_compactor_config
# ---------------------------------------------------------------------------


class TestSelectCompactorConfig:
    def test_short_session_returns_noop(self):
        events = _make_events(10)
        config = select_compactor_config(events)
        assert isinstance(config, NoOpCompactorConfig)

    def test_short_session_returns_fallback(self):
        fallback = RecentEventsCompactorConfig(keep_first=1, max_events=50)
        events = _make_events(10)
        config = select_compactor_config(events, fallback=fallback)
        assert config is fallback

    def test_high_error_ratio_returns_recent(self):
        # Need error_ratio >= 0.15. With 50 events, need >=8 errors
        events = _make_error_heavy_events(50, 10)
        config = select_compactor_config(events)
        assert isinstance(config, RecentEventsCompactorConfig)

    def test_long_session_with_llm_returns_smart(self):
        events = _make_events(_LONG_SESSION + 10)
        config = select_compactor_config(events, llm_config='condenser_llm')
        assert isinstance(config, SmartCompactorConfig)
        assert config.llm_config == 'condenser_llm'

    def test_long_session_no_llm_returns_amortized(self):
        events = _make_events(_LONG_SESSION + 10)
        config = select_compactor_config(events, llm_config=None)
        assert isinstance(config, AmortizedPruningCompactorConfig)

    def test_medium_session_returns_observation_masking(self):
        events = _make_events(_MEDIUM_SESSION + 10)
        config = select_compactor_config(events)
        assert isinstance(config, ObservationMaskingCompactorConfig)

    def test_below_short_returns_noop(self):
        events = _make_events(_SHORT_SESSION - 5)
        config = select_compactor_config(events)
        assert isinstance(config, NoOpCompactorConfig)

    def test_error_priority_over_length(self):
        """High error ratio should take precedence over session length."""
        # Long session with high error ratio
        total = _LONG_SESSION + 10
        error_count = int(total * _HIGH_ERROR_RATIO) + 5
        events = _make_error_heavy_events(total, error_count)
        config = select_compactor_config(events, llm_config='llm')
        # Error heuristic should fire before long-session heuristic
        assert isinstance(config, RecentEventsCompactorConfig)


# ---------------------------------------------------------------------------
# AutoCompactorConfig
# ---------------------------------------------------------------------------


class TestAutoCompactorConfig:
    def test_type_field(self):
        cfg = AutoCompactorConfig()
        assert cfg.type == 'auto'

    def test_with_llm_config(self):
        cfg = AutoCompactorConfig(llm_config='my_llm')
        assert cfg.llm_config == 'my_llm'

    def test_rejects_extra_fields(self):
        with pytest.raises(Exception):
            AutoCompactorConfig.model_validate({'type': 'auto', 'unknown_field': True})
