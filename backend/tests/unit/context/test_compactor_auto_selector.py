"""Tests for backend.context.compactor.strategies.auto_selector - task-aware compactor selection."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.context.compactor.compactor import Compaction, RollingCompactor
from backend.context.compactor.strategies.auto_compactor import AutoCompactor
from backend.context.compactor.strategies.auto_selector import (
    _HIGH_ERROR_RATIO,
    _LONG_SESSION,
    _MEDIUM_SESSION,
    _SHORT_SESSION,
    TaskSignals,
    compute_signals,
    select_compactor_config,
)
from backend.context.view import View
from backend.core.config.compactor_config import (
    AmortizedPruningCompactorConfig,
    AutoCompactorConfig,
    NoOpCompactorConfig,
    ObservationMaskingCompactorConfig,
    RecentEventsCompactorConfig,
    SmartCompactorConfig,
    StructuredSummaryCompactorConfig,
)
from backend.core.config.llm_config import LLMConfig
from backend.ledger.action import CmdRunAction, MessageAction
from backend.ledger.action.agent import CondensationAction
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

    def test_long_session_with_llm_defaults_to_amortized(self):
        events = _make_events(_LONG_SESSION + 10)
        config = select_compactor_config(events, llm_config='condenser_llm')
        assert isinstance(config, AmortizedPruningCompactorConfig)

    def test_long_session_with_llm_hot_path_allowed_returns_smart(self):
        events = _make_events(_LONG_SESSION + 10)
        config = select_compactor_config(
            events,
            llm_config='condenser_llm',
            allow_llm_hot_path=True,
        )
        assert isinstance(config, SmartCompactorConfig)
        assert config.llm_config == 'condenser_llm'

    def test_long_session_with_function_calling_hot_path_returns_structured(self):
        events = _make_events(_LONG_SESSION + 10)
        config = select_compactor_config(
            events,
            llm_config='condenser_llm',
            supports_function_calling=True,
            allow_llm_hot_path=True,
        )
        assert isinstance(config, StructuredSummaryCompactorConfig)
        assert config.llm_config == 'condenser_llm'

    def test_long_session_no_llm_returns_amortized(self):
        events = _make_events(_LONG_SESSION + 10)
        config = select_compactor_config(events, llm_config=None)
        assert isinstance(config, AmortizedPruningCompactorConfig)

    def test_medium_session_returns_microcompact(self):
        events = _make_events(_MEDIUM_SESSION + 10)
        config = select_compactor_config(events)
        from backend.core.config.compactor_config import MicrocompactCompactorConfig

        assert isinstance(config, MicrocompactCompactorConfig)

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
# AutoCompactor
# ---------------------------------------------------------------------------


class TestAutoCompactor:
    async def test_explicit_request_bypasses_short_session_noop(self):
        auto = AutoCompactor(llm_config='condenser_llm', llm_registry=MagicMock())
        view = View(
            events=_make_events(5),
            unhandled_condensation_request=True,
        )
        action = CondensationAction(pruned_event_ids=[1])
        delegate = MagicMock()
        delegate.compact = AsyncMock(return_value=Compaction(action=action))

        with patch(
            'backend.context.compactor.strategies.auto_compactor.Compactor.from_config',
            return_value=delegate,
        ) as factory:
            result = await auto.compact(view)

        config = factory.call_args.args[0]
        assert isinstance(config, StructuredSummaryCompactorConfig)
        assert isinstance(result, Compaction)
        assert result.action is action

    async def test_explicit_request_forces_rolling_delegate_compaction(self):
        auto = AutoCompactor(llm_config=None, llm_registry=MagicMock())
        view = View(
            events=_make_events(5),
            unhandled_condensation_request=True,
        )
        action = CondensationAction(pruned_event_ids=[1])
        compaction = Compaction(action=action)
        delegate = MagicMock(spec=RollingCompactor)
        delegate.compact = AsyncMock(return_value=view)
        delegate.get_compaction = AsyncMock(return_value=compaction)

        with patch(
            'backend.context.compactor.strategies.auto_compactor.Compactor.from_config',
            return_value=delegate,
        ):
            result = await auto.compact(view)

        delegate.get_compaction.assert_awaited_once_with(view)
        assert result is compaction

    async def test_normal_long_session_with_llm_uses_bounded_delegate(self):
        auto = AutoCompactor(llm_config='condenser_llm', llm_registry=MagicMock())
        view = View(events=_make_events(_LONG_SESSION + 10))
        delegate = MagicMock()
        delegate.compact = AsyncMock(return_value=view)

        with patch(
            'backend.context.compactor.strategies.auto_compactor.Compactor.from_config',
            return_value=delegate,
        ) as factory:
            result = await auto.compact(view)

        config = factory.call_args.args[0]
        assert isinstance(config, AmortizedPruningCompactorConfig)
        assert result is view

    async def test_normal_long_session_can_opt_into_llm_hot_path(self):
        auto = AutoCompactor(
            llm_config='condenser_llm',
            llm_registry=MagicMock(),
            allow_llm_hot_path=True,
        )
        view = View(events=_make_events(_LONG_SESSION + 10))
        delegate = MagicMock()
        delegate.compact = AsyncMock(return_value=view)

        with patch(
            'backend.context.compactor.strategies.auto_compactor.Compactor.from_config',
            return_value=delegate,
        ) as factory:
            result = await auto.compact(view)

        config = factory.call_args.args[0]
        assert isinstance(config, SmartCompactorConfig)
        assert result is view

    async def test_background_long_session_uses_structured_when_supported(self):
        llm_config = LLMConfig.model_validate({'model': 'openai/gpt-4o'})
        auto = AutoCompactor(llm_config=llm_config, llm_registry=MagicMock())
        view = View(events=_make_events(_LONG_SESSION + 10))
        delegate = MagicMock()
        delegate.compact = AsyncMock(return_value=view)

        with patch(
            'backend.context.compactor.strategies.auto_compactor.Compactor.from_config',
            return_value=delegate,
        ) as factory:
            result = await auto.compact_background(view)

        config = factory.call_args.args[0]
        assert isinstance(config, StructuredSummaryCompactorConfig)
        assert result is view

    async def test_background_falls_back_when_structured_delegate_unavailable(self):
        llm_config = LLMConfig.model_validate({'model': 'openai/gpt-4o'})
        auto = AutoCompactor(llm_config=llm_config, llm_registry=MagicMock())
        view = View(events=_make_events(_LONG_SESSION + 10))
        delegate = MagicMock()
        delegate.compact = AsyncMock(return_value=view)

        def make_delegate(config, registry):
            del registry
            if isinstance(config, StructuredSummaryCompactorConfig):
                raise ValueError('function calling unavailable')
            return delegate

        with patch(
            'backend.context.compactor.strategies.auto_compactor.Compactor.from_config',
            side_effect=make_delegate,
        ) as factory:
            result = await auto.compact_background(view)

        configs = [call.args[0] for call in factory.call_args_list]
        assert isinstance(configs[0], StructuredSummaryCompactorConfig)
        assert isinstance(configs[1], SmartCompactorConfig)
        assert result is view

    def test_status_prediction_for_normal_long_session(self):
        auto = AutoCompactor(llm_config='condenser_llm', llm_registry=MagicMock())
        view = View(events=_make_events(_LONG_SESSION + 10))

        assert auto.should_emit_compaction_status(view) is True

    def test_status_prediction_skips_medium_masking_session(self):
        auto = AutoCompactor(llm_config='condenser_llm', llm_registry=MagicMock())
        view = View(events=_make_events(_MEDIUM_SESSION + 10))

        assert auto.should_emit_compaction_status(view) is False


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

    def test_llm_hot_path_enabled_by_default(self):
        cfg = AutoCompactorConfig()
        assert cfg.allow_llm_hot_path is True

    def test_can_disable_llm_hot_path(self):
        cfg = AutoCompactorConfig(allow_llm_hot_path=False)
        assert cfg.allow_llm_hot_path is False

    def test_rejects_extra_fields(self):
        with pytest.raises(Exception):
            AutoCompactorConfig.model_validate({'type': 'auto', 'unknown_field': True})
