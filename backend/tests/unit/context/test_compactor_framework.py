"""Tests for backend.context.compactor.compactor - compactor framework classes."""

from __future__ import annotations

from unittest.mock import MagicMock
from typing import cast

import pytest
from backend.core.config.compactor_config import CompactorConfig

from backend.context.compactor.compactor import (
    COMPACTOR_METADATA_KEY,
    COMPACTOR_REGISTRY,
    BaseLLMCompactor,
    Compaction,
    Compactor,
    MAX_COMPACTOR_META_BATCHES,
    get_compaction_metadata,
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
# get_compaction_metadata
# ===================================================================


class TestGetCompactionMetadata:
    def test_empty_state(self):
        state = _make_state()
        assert get_compaction_metadata(state) == []

    def test_with_metadata(self):
        state = _make_state({COMPACTOR_METADATA_KEY: [{"batch": 1}]})
        assert get_compaction_metadata(state) == [{"batch": 1}]


# ===================================================================
# Compactor.add_metadata / write_metadata
# ===================================================================


class ConcreteCompactor(Compactor):
    """Non-abstract compactor for testing."""

    def compact(self, view):
        return view


class TestCompactorMetadata:
    def test_add_and_write(self):
        c = ConcreteCompactor()
        state = _make_state()
        c.add_metadata("key1", "value1")
        c.add_metadata("key2", 42)
        c.write_metadata(state)
        meta = state.extra_data[COMPACTOR_METADATA_KEY]
        assert len(meta) == 1
        assert meta[0] == {"key1": "value1", "key2": 42}

    def test_write_clears_batch(self):
        c = ConcreteCompactor()
        state = _make_state()
        c.add_metadata("a", 1)
        c.write_metadata(state)
        # Second write should produce empty batch (nothing added)
        c.write_metadata(state)
        meta = state.extra_data[COMPACTOR_METADATA_KEY]
        assert len(meta) == 1  # Only the first batch

    def test_eviction_on_max_batches(self):
        c = ConcreteCompactor()
        state = _make_state(
            {
                COMPACTOR_METADATA_KEY: [
                    {"i": i} for i in range(MAX_COMPACTOR_META_BATCHES)
                ]
            }
        )
        c.add_metadata("new", True)
        c.write_metadata(state)
        meta = state.extra_data[COMPACTOR_METADATA_KEY]
        assert len(meta) == MAX_COMPACTOR_META_BATCHES
        assert meta[-1] == {"new": True}

    def test_metadata_batch_context_manager(self):
        c = ConcreteCompactor()
        state = _make_state()
        with c.metadata_batch(state):
            c.add_metadata("ctx", "test")
        meta = state.extra_data[COMPACTOR_METADATA_KEY]
        assert len(meta) == 1
        assert meta[0]["ctx"] == "test"


# ===================================================================
# Compactor.register_config / from_config
# ===================================================================


class TestCompactorRegistry:
    def test_register_and_from_config(self):
        # Create a dummy config type
        class DummyConfig:
            pass

        class DummyCompactor(Compactor):
            def compact(self, view):
                return view

            @classmethod
            def from_config(cls, config, llm_registry):
                return cls()

        # Register
        DummyCompactor.register_config(cast(type[CompactorConfig], DummyConfig))
        try:
            assert DummyConfig in COMPACTOR_REGISTRY
            # from_config should work
            instance = Compactor.from_config(
                cast(CompactorConfig, DummyConfig()), MagicMock()
            )
            assert isinstance(instance, DummyCompactor)
        finally:
            # Cleanup global registry
            COMPACTOR_REGISTRY.pop(cast(type[CompactorConfig], DummyConfig), None)

    def test_register_duplicate_raises(self):
        class DuplicateConfig:
            pass

        ConcreteCompactor.register_config(
            cast(type[CompactorConfig], DuplicateConfig)
        )
        try:
            with pytest.raises(ValueError, match="already registered"):
                ConcreteCompactor.register_config(
                    cast(type[CompactorConfig], DuplicateConfig)
                )
        finally:
            COMPACTOR_REGISTRY.pop(cast(type[CompactorConfig], DuplicateConfig), None)

    def test_from_config_unknown_raises(self):
        class UnknownConfig:
            pass

        with pytest.raises(ValueError, match="Unknown compactor config"):
            Compactor.from_config(cast(CompactorConfig, UnknownConfig()), MagicMock())


# ===================================================================
# BaseLLMCompactor
# ===================================================================


class ConcreteLLMCompactor(BaseLLMCompactor):
    """Non-abstract LLM compactor for testing."""

    def get_compaction(self, view):
        return Compaction(
            action=MagicMock(
                pruned_events_start_id=0,
                pruned_events_end_id=1,
                summary="summarized",
                summary_offset=0,
            )
        )


class TestBaseLLMCompactor:
    def test_init_basic(self):
        c = ConcreteLLMCompactor(llm=None, max_size=50, keep_first=2)
        assert c.max_size == 50
        assert c.keep_first == 2

    def test_max_size_must_be_positive(self):
        with pytest.raises(ValueError, match="max_size.*must be positive"):
            ConcreteLLMCompactor(llm=None, max_size=0)

    def test_keep_first_cannot_be_negative(self):
        with pytest.raises(ValueError, match="keep_first.*cannot be negative"):
            ConcreteLLMCompactor(llm=None, max_size=10, keep_first=-1)

    def test_keep_first_at_most_half_max_ok(self):
        # keep_first may be at most half of max_size.
        ConcreteLLMCompactor(llm=None, max_size=10, keep_first=5)

    def test_keep_first_greater_than_half_max_raises(self):
        with pytest.raises(ValueError, match="keep_first.*half"):
            ConcreteLLMCompactor(llm=None, max_size=10, keep_first=6)

    def test_should_compact(self):
        c = ConcreteLLMCompactor(llm=None, max_size=5, keep_first=1)
        events = _make_events(6)
        view = View(events=events)
        assert c.should_compact(view) is True

    def test_should_not_compact(self):
        c = ConcreteLLMCompactor(llm=None, max_size=10, keep_first=1)
        events = _make_events(3)
        view = View(events=events)
        assert c.should_compact(view) is False

    def test_estimate_view_tokens(self):
        events = _make_events(5)
        view = View(events=events)
        tokens = BaseLLMCompactor.estimate_view_tokens(view)
        assert tokens >= 1

    def test_estimate_empty_view(self):
        view = View(events=[])
        tokens = BaseLLMCompactor.estimate_view_tokens(view)
        assert tokens == 1

    def test_exceeds_token_budget_none(self):
        c = ConcreteLLMCompactor(llm=None, max_size=100)
        c.token_budget = None
        view = View(events=_make_events(5))
        assert c._exceeds_token_budget(view) is False

    def test_exceeds_token_budget_true(self):
        c = ConcreteLLMCompactor(llm=None, max_size=100)
        c.token_budget = 1  # Very small budget
        view = View(events=_make_events(5))
        assert c._exceeds_token_budget(view) is True

    def test_truncate(self):
        c = ConcreteLLMCompactor(llm=None, max_size=100, max_event_length=10)
        result = c._truncate("a" * 200)
        # truncate_content adds wrapper text, but result should be shorter than original
        assert len(result) < 200

    def test_sanitize_workspace_paths_rewrites_app_workspace_paths(self):
        result = BaseLLMCompactor._sanitize_workspace_paths(
            "see /tmp/app_workspace_sid_123/src/main.py for details"
        )

        assert result == "see /workspace for details"


# ===================================================================
# Compaction model
# ===================================================================


class TestCompaction:
    def test_compaction_creation(self):
        from backend.ledger.action.agent import CondensationAction

        action = CondensationAction(
            pruned_events_start_id=0,
            pruned_events_end_id=10,
            summary="Events were condensed",
            summary_offset=1,
        )
        c = Compaction(action=action)
        assert c.action.summary == "Events were condensed"
        assert c.action.pruned_events_start_id == 0
