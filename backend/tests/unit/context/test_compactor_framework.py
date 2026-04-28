"""Tests for backend.context.compactor.compactor - compactor framework classes."""

from __future__ import annotations

import builtins
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from backend.context.compactor.compactor import (
    COMPACTOR_METADATA_KEY,
    COMPACTOR_REGISTRY,
    MAX_COMPACTOR_META_BATCHES,
    BaseLLMCompactor,
    Compaction,
    Compactor,
    get_compaction_metadata,
)
from backend.context.view import View
from backend.core.config.compactor_config import CompactorConfig
from backend.core.config.llm_config import LLMConfig
from backend.ledger.action import MessageAction
from backend.ledger.action.agent import CondensationAction

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
        e = MessageAction(content=f'msg-{i}')
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
        state = _make_state({COMPACTOR_METADATA_KEY: [{'batch': 1}]})
        assert get_compaction_metadata(state) == [{'batch': 1}]


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
        c.add_metadata('key1', 'value1')
        c.add_metadata('key2', 42)
        c.write_metadata(state)
        meta = state.extra_data[COMPACTOR_METADATA_KEY]
        assert len(meta) == 1
        assert meta[0] == {'key1': 'value1', 'key2': 42}

    def test_write_clears_batch(self):
        c = ConcreteCompactor()
        state = _make_state()
        c.add_metadata('a', 1)
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
                    {'i': i} for i in range(MAX_COMPACTOR_META_BATCHES)
                ]
            }
        )
        c.add_metadata('new', True)
        c.write_metadata(state)
        meta = state.extra_data[COMPACTOR_METADATA_KEY]
        assert len(meta) == MAX_COMPACTOR_META_BATCHES
        assert meta[-1] == {'new': True}

    def test_metadata_batch_context_manager(self):
        c = ConcreteCompactor()
        state = _make_state()
        with c.metadata_batch(state):
            c.add_metadata('ctx', 'test')
        meta = state.extra_data[COMPACTOR_METADATA_KEY]
        assert len(meta) == 1
        assert meta[0]['ctx'] == 'test'

    def test_compacted_history_populates_llm_metadata(self):
        llm = MagicMock()
        llm.config.model = 'openai/gpt-4'
        c = ConcreteLLMCompactor(llm=llm, max_size=100, keep_first=1)
        state = _make_state()
        state.view = View(events=_make_events(2))
        state.to_llm_metadata.return_value = {'model': 'openai/gpt-4'}

        result = c.compacted_history(state)

        assert result == state.view
        assert c.llm_metadata == {'model': 'openai/gpt-4'}
        state.to_llm_metadata.assert_called_once_with(
            model_name='openai/gpt-4', agent_name='compactor'
        )

    def test_llm_metadata_warns_when_empty(self):
        c = ConcreteCompactor()
        with patch('backend.context.compactor.compactor.logger.warning') as mock_warn:
            assert c.llm_metadata == {}
        mock_warn.assert_called_once()


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

        ConcreteCompactor.register_config(cast(type[CompactorConfig], DuplicateConfig))
        try:
            with pytest.raises(ValueError, match='already registered'):
                ConcreteCompactor.register_config(
                    cast(type[CompactorConfig], DuplicateConfig)
                )
        finally:
            COMPACTOR_REGISTRY.pop(cast(type[CompactorConfig], DuplicateConfig), None)

    def test_from_config_unknown_raises(self):
        class UnknownConfig:
            pass

        with pytest.raises(ValueError, match='Unknown compactor config'):
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
                summary='summarized',
                summary_offset=0,
            )
        )


class TestBaseLLMCompactor:
    def test_init_basic(self):
        c = ConcreteLLMCompactor(llm=None, max_size=50, keep_first=2)
        assert c.max_size == 50
        assert c.keep_first == 2

    def test_max_size_must_be_positive(self):
        with pytest.raises(ValueError, match='max_size.*must be positive'):
            ConcreteLLMCompactor(llm=None, max_size=0)

    def test_keep_first_cannot_be_negative(self):
        with pytest.raises(ValueError, match='keep_first.*cannot be negative'):
            ConcreteLLMCompactor(llm=None, max_size=10, keep_first=-1)

    def test_keep_first_at_most_half_max_ok(self):
        # keep_first may be at most half of max_size.
        ConcreteLLMCompactor(llm=None, max_size=10, keep_first=5)

    def test_keep_first_greater_than_half_max_raises(self):
        with pytest.raises(ValueError, match='keep_first.*half'):
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
        result = c._truncate('a' * 200)
        # truncate_content adds wrapper text, but result should be shorter than original
        assert len(result) < 200

    def test_sanitize_workspace_paths_rewrites_app_workspace_paths(self):
        result = BaseLLMCompactor._sanitize_workspace_paths(
            'see /tmp/app_workspace_sid_123/src/main.py for details'
        )

        assert result == 'see [project] for details'

    def test_from_config_with_llm_config_object_derives_budget(self):
        cfg = MagicMock()
        cfg.llm_config = LLMConfig.model_validate({'model': 'openai/gpt-4'})
        cfg.max_size = 40
        cfg.keep_first = 2
        cfg.token_budget = None
        llm_registry = MagicMock()
        llm_instance = MagicMock()
        llm_instance.config.max_input_tokens = 1000
        llm_registry.get_llm.return_value = llm_instance

        compactor = ConcreteLLMCompactor.from_config(cfg, llm_registry)

        assert compactor.token_budget == 800
        call = llm_registry.get_llm.call_args
        assert call.kwargs['service_id'] == 'compactor_openai/gpt-4'
        assert call.kwargs['config'].caching_prompt is False

    def test_from_config_with_named_llm_config_uses_registry_lookup(self):
        cfg = MagicMock()
        cfg.llm_config = 'planner'
        cfg.max_size = 40
        cfg.keep_first = 2
        cfg.token_budget = 123
        llm_registry = MagicMock()
        llm_registry.config.get_llm_config.return_value = LLMConfig.model_validate(
            {'model': 'openai/gpt-4o'}
        )
        llm_registry.get_llm.return_value = MagicMock(config=MagicMock(max_input_tokens=None))

        compactor = ConcreteLLMCompactor.from_config(cfg, llm_registry)

        assert compactor.token_budget == 123
        llm_registry.config.get_llm_config.assert_called_once_with('planner')
        assert llm_registry.get_llm.call_args.kwargs['service_id'] == 'compactor_planner'

    def test_get_extra_config_args_includes_max_event_length(self):
        cfg = MagicMock()
        cfg.max_event_length = 321
        assert ConcreteLLMCompactor._get_extra_config_args(cfg) == {
            'max_event_length': 321
        }

    def test_add_response_metadata_records_response_and_metrics(self):
        c = ConcreteLLMCompactor(llm=MagicMock(), max_size=10)
        c.llm.metrics.get.return_value = {'tokens': 5}

        with patch(
            'backend.core.pydantic_compat.model_dump_with_options',
            return_value={'ok': True},
        ):
            c._add_response_metadata(MagicMock())

        assert c._metadata_batch['response'] == {'ok': True}
        assert c._metadata_batch['metrics'] == {'tokens': 5}

    def test_create_compaction_result_sanitizes_summary_and_uses_event_range(self):
        c = ConcreteLLMCompactor(llm=None, max_size=10, keep_first=2)
        events = _make_events(3)

        result = c._create_compaction_result(events, '/tmp/app_workspace_sid_1/notes')

        assert result.action.pruned_events_start_id == 0
        assert result.action.pruned_events_end_id == 2
        assert result.action.summary == '[project]'
        assert result.action.summary_offset == 2

    def test_sanitize_workspace_paths_precise_env_and_passthrough(self, monkeypatch):
        monkeypatch.setenv('APP_WORKSPACE_DIR', r'C:\temp\app_workspace_sid_123')
        precise = BaseLLMCompactor._sanitize_workspace_paths(
            r'paths: C:\temp\app_workspace_sid_123 and C:/temp/app_workspace_sid_123'
        )
        assert precise == 'paths: [project] and [project]'

        monkeypatch.delenv('APP_WORKSPACE_DIR', raising=False)
        assert BaseLLMCompactor._sanitize_workspace_paths('nothing to replace') == 'nothing to replace'
        assert BaseLLMCompactor._sanitize_workspace_paths('app_workspace_sid_123/file.txt') == '[project]'

    def test_estimate_view_tokens_falls_back_when_serialization_fails(self):
        view = View(events=_make_events(1))
        with patch(
            'backend.context.compactor.compactor.event_to_dict',
            side_effect=RuntimeError('boom'),
        ), patch.object(BaseLLMCompactor, '_get_tokenizer', return_value=None):
            assert BaseLLMCompactor.estimate_view_tokens(view) >= 1

    def test_estimate_view_tokens_falls_back_when_tokenizer_encode_fails(self):
        view = View(events=_make_events(1))
        tokenizer = MagicMock()
        tokenizer.encode.side_effect = RuntimeError('bad encode')
        with patch.object(BaseLLMCompactor, '_get_tokenizer', return_value=tokenizer):
            assert BaseLLMCompactor.estimate_view_tokens(view) >= 1

    def test_get_tokenizer_returns_none_when_import_fails(self):
        BaseLLMCompactor._get_tokenizer.cache_clear()
        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == 'tiktoken':
                raise ImportError('missing')
            return original_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=fake_import):
            assert BaseLLMCompactor._get_tokenizer() is None
        BaseLLMCompactor._get_tokenizer.cache_clear()

    def test_model_token_multiplier_handles_broken_llm(self):
        class _BrokenLLM:
            @property
            def config(self):
                raise RuntimeError('bad llm')

        c = ConcreteLLMCompactor(llm=None, max_size=10)
        c.llm = _BrokenLLM()
        with patch(
            'backend.inference.provider_capabilities.model_token_correction',
            return_value=(1.23, None),
        ):
            assert c._model_token_multiplier() == 1.23

    def test_exceeds_token_budget_false_when_under_limit(self):
        c = ConcreteLLMCompactor(llm=None, max_size=10)
        c.token_budget = 100
        with patch.object(ConcreteLLMCompactor, 'estimate_view_tokens', return_value=10):
            assert c._exceeds_token_budget(View(events=_make_events(2))) is False

    def test_compact_returns_view_or_compaction_based_on_thresholds(self):
        c = ConcreteLLMCompactor(llm=None, max_size=10)
        compacted_events = _make_events(2)
        view = View(events=_make_events(3))

        with patch.object(c._compactor, 'compact', return_value=compacted_events), patch.object(
            c, 'should_compact', return_value=False
        ), patch.object(c, '_exceeds_token_budget', return_value=False):
            result = c.compact(view)
            assert isinstance(result, View)
            assert result.events == compacted_events

        compaction = Compaction(
            action=CondensationAction(
                pruned_events_start_id=0,
                pruned_events_end_id=1,
            )
        )
        with patch.object(c._compactor, 'compact', return_value=view.events), patch.object(
            c, 'should_compact', return_value=True
        ), patch.object(c, '_exceeds_token_budget', return_value=False), patch.object(
            c, 'get_compaction', return_value=compaction
        ):
            assert c.compact(view) is compaction


# ===================================================================
# Compaction model
# ===================================================================


class TestCompaction:
    def test_compaction_creation(self):
        from backend.ledger.action.agent import CondensationAction

        action = CondensationAction(
            pruned_events_start_id=0,
            pruned_events_end_id=10,
            summary='Events were condensed',
            summary_offset=1,
        )
        c = Compaction(action=action)
        assert c.action.summary == 'Events were condensed'
        assert c.action.pruned_events_start_id == 0
