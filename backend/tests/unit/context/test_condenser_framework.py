"""Tests for backend.context.condenser.condenser — Condenser framework classes."""

from __future__ import annotations

from unittest.mock import MagicMock
from typing import cast

import pytest
from backend.core.config.condenser_config import CondenserConfig

from backend.context.condenser.condenser import (
    CONDENSER_METADATA_KEY,
    CONDENSER_REGISTRY,
    BaseLLMCondenser,
    Condensation,
    Condenser,
    MAX_CONDENSER_META_BATCHES,
    get_condensation_metadata,
)
from backend.context.view import View
from backend.ledger.action import MessageAction


# ===================================================================
# Helpers
# ===================================================================


def _make_state(extra_data: dict | None = None):
    """Create a fake State with extra_data dict."""
    state = MagicMock()
    state.extra_data = extra_data or {}
    state.set_extra = MagicMock(
        side_effect=lambda k, v, **kw: state.extra_data.__setitem__(k, v)
    )
    return state


def _make_events(n: int) -> list:
    """Create n MessageAction events for building a View."""
    events = []
    for i in range(n):
        e = MessageAction(content=f"msg-{i}")
        e._id = i
        events.append(e)
    return events


# ===================================================================
# get_condensation_metadata
# ===================================================================


class TestGetCondensationMetadata:
    def test_empty_state(self):
        state = _make_state()
        assert get_condensation_metadata(state) == []

    def test_with_metadata(self):
        state = _make_state({CONDENSER_METADATA_KEY: [{"batch": 1}]})
        assert get_condensation_metadata(state) == [{"batch": 1}]


# ===================================================================
# Condenser.add_metadata / write_metadata
# ===================================================================


class ConcreteCondenser(Condenser):
    """Non-abstract condenser for testing."""

    def condense(self, view):
        return view


class TestCondenserMetadata:
    def test_add_and_write(self):
        c = ConcreteCondenser()
        state = _make_state()
        c.add_metadata("key1", "value1")
        c.add_metadata("key2", 42)
        c.write_metadata(state)
        meta = state.extra_data[CONDENSER_METADATA_KEY]
        assert len(meta) == 1
        assert meta[0] == {"key1": "value1", "key2": 42}

    def test_write_clears_batch(self):
        c = ConcreteCondenser()
        state = _make_state()
        c.add_metadata("a", 1)
        c.write_metadata(state)
        # Second write should produce empty batch (nothing added)
        c.write_metadata(state)
        meta = state.extra_data[CONDENSER_METADATA_KEY]
        assert len(meta) == 1  # Only the first batch

    def test_eviction_on_max_batches(self):
        c = ConcreteCondenser()
        state = _make_state(
            {
                CONDENSER_METADATA_KEY: [
                    {"i": i} for i in range(MAX_CONDENSER_META_BATCHES)
                ]
            }
        )
        c.add_metadata("new", True)
        c.write_metadata(state)
        meta = state.extra_data[CONDENSER_METADATA_KEY]
        assert len(meta) == MAX_CONDENSER_META_BATCHES
        assert meta[-1] == {"new": True}

    def test_metadata_batch_context_manager(self):
        c = ConcreteCondenser()
        state = _make_state()
        with c.metadata_batch(state):
            c.add_metadata("ctx", "test")
        meta = state.extra_data[CONDENSER_METADATA_KEY]
        assert len(meta) == 1
        assert meta[0]["ctx"] == "test"


# ===================================================================
# Condenser.register_config / from_config
# ===================================================================


class TestCondenserRegistry:
    def test_register_and_from_config(self):
        # Create a dummy config type
        class DummyConfig:
            pass

        class DummyCondenser(Condenser):
            def condense(self, view):
                return view

            @classmethod
            def from_config(cls, config, llm_registry):
                return cls()

        # Register
        DummyCondenser.register_config(cast(type[CondenserConfig], DummyConfig))
        try:
            assert DummyConfig in CONDENSER_REGISTRY
            # from_config should work
            instance = Condenser.from_config(
                cast(CondenserConfig, DummyConfig()), MagicMock()
            )
            assert isinstance(instance, DummyCondenser)
        finally:
            # Cleanup global registry
            CONDENSER_REGISTRY.pop(cast(type[CondenserConfig], DummyConfig), None)

    def test_register_duplicate_raises(self):
        class DuplicateConfig:
            pass

        ConcreteCondenser.register_config(
            cast(type[CondenserConfig], DuplicateConfig)
        )
        try:
            with pytest.raises(ValueError, match="already registered"):
                ConcreteCondenser.register_config(
                    cast(type[CondenserConfig], DuplicateConfig)
                )
        finally:
            CONDENSER_REGISTRY.pop(cast(type[CondenserConfig], DuplicateConfig), None)

    def test_from_config_unknown_raises(self):
        class UnknownConfig:
            pass

        with pytest.raises(ValueError, match="Unknown condenser config"):
            Condenser.from_config(cast(CondenserConfig, UnknownConfig()), MagicMock())


# ===================================================================
# BaseLLMCondenser
# ===================================================================


class ConcreteLLMCondenser(BaseLLMCondenser):
    """Non-abstract LLM condenser for testing."""

    def get_condensation(self, view):
        return Condensation(
            action=MagicMock(
                forgotten_events_start_id=0,
                forgotten_events_end_id=1,
                summary="summarized",
                summary_offset=0,
            )
        )


class TestBaseLLMCondenser:
    def test_init_basic(self):
        c = ConcreteLLMCondenser(llm=None, max_size=50, keep_first=2)
        assert c.max_size == 50
        assert c.keep_first == 2

    def test_max_size_must_be_positive(self):
        with pytest.raises(ValueError, match="max_size.*must be positive"):
            ConcreteLLMCondenser(llm=None, max_size=0)

    def test_keep_first_cannot_be_negative(self):
        with pytest.raises(ValueError, match="keep_first.*cannot be negative"):
            ConcreteLLMCondenser(llm=None, max_size=10, keep_first=-1)

    def test_keep_first_at_most_half_max_ok(self):
        # keep_first may be at most half of max_size.
        ConcreteLLMCondenser(llm=None, max_size=10, keep_first=5)

    def test_keep_first_greater_than_half_max_raises(self):
        with pytest.raises(ValueError, match="keep_first.*half"):
            ConcreteLLMCondenser(llm=None, max_size=10, keep_first=6)

    def test_should_condense(self):
        c = ConcreteLLMCondenser(llm=None, max_size=5, keep_first=1)
        events = _make_events(6)
        view = View(events=events)
        assert c.should_condense(view) is True

    def test_should_not_condense(self):
        c = ConcreteLLMCondenser(llm=None, max_size=10, keep_first=1)
        events = _make_events(3)
        view = View(events=events)
        assert c.should_condense(view) is False

    def test_estimate_view_tokens(self):
        events = _make_events(5)
        view = View(events=events)
        tokens = BaseLLMCondenser.estimate_view_tokens(view)
        assert tokens >= 1

    def test_estimate_empty_view(self):
        view = View(events=[])
        tokens = BaseLLMCondenser.estimate_view_tokens(view)
        assert tokens == 1

    def test_exceeds_token_budget_none(self):
        c = ConcreteLLMCondenser(llm=None, max_size=100)
        c.token_budget = None
        view = View(events=_make_events(5))
        assert c._exceeds_token_budget(view) is False

    def test_exceeds_token_budget_true(self):
        c = ConcreteLLMCondenser(llm=None, max_size=100)
        c.token_budget = 1  # Very small budget
        view = View(events=_make_events(5))
        assert c._exceeds_token_budget(view) is True

    def test_truncate(self):
        c = ConcreteLLMCondenser(llm=None, max_size=100, max_event_length=10)
        result = c._truncate("a" * 200)
        # truncate_content adds wrapper text, but result should be shorter than original
        assert len(result) < 200


# ===================================================================
# Condensation model
# ===================================================================


class TestCondensation:
    def test_condensation_creation(self):
        from backend.ledger.action.agent import CondensationAction

        action = CondensationAction(
            forgotten_events_start_id=0,
            forgotten_events_end_id=10,
            summary="Events were condensed",
            summary_offset=1,
        )
        c = Condensation(action=action)
        assert c.action.summary == "Events were condensed"
        assert c.action.forgotten_events_start_id == 0
