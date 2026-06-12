"""Tests for family-driven reasoning wire mapping."""

from __future__ import annotations

import pytest

from backend.inference.catalog_loader import (
    ModelEntry,
    apply_model_param_overrides,
    lookup,
    sanitize_call_kwargs_for_provider,
)
from backend.inference.reasoning import (
    WIRE_ANTHROPIC_ADAPTIVE,
    WIRE_OPENAI_REASONING_EFFORT,
    apply_reasoning_plan,
    infer_family,
    resolve_reasoning_plan,
    supports_reasoning,
)


def _entry(
    name: str = 'test-model',
    provider: str = 'opencode',
    **kwargs,
) -> ModelEntry:
    return ModelEntry(name=name, provider=provider, **kwargs)


class TestSupportsReasoning:
    def test_metadata_capabilities_reasoning(self):
        entry = _entry(
            metadata={'capabilities': {'reasoning': True}, 'family': 'deepseek-flash-free'}
        )
        assert supports_reasoning(entry) is True

    def test_inferred_from_openai_gpt5(self):
        entry = _entry(
            name='gpt-5',
            provider='openai',
            supports_reasoning_effort=True,
        )
        assert supports_reasoning(entry) is True

    def test_inferred_claude_without_metadata(self):
        entry = _entry(name='claude-sonnet-4-6', provider='anthropic')
        assert supports_reasoning(entry) is True
        assert infer_family(entry) == 'claude-sonnet'


class TestResolveReasoningPlan:
    def test_opencode_deepseek_flash_free_reasoning_effort(self):
        entry = lookup('opencode/deepseek-v4-flash-free')
        assert entry is not None
        plan = resolve_reasoning_plan(entry, 'high')
        assert plan.enabled is True
        assert plan.wire == WIRE_OPENAI_REASONING_EFFORT
        assert plan.resolved_effort == 'high'
        assert 'thinking' not in plan.kwargs_patch
        assert plan.kwargs_patch.get('reasoning_effort') == 'high'

    def test_openai_gpt5_reasoning_effort(self):
        entry = lookup('openai/gpt-5')
        assert entry is not None
        plan = resolve_reasoning_plan(entry, 'medium')
        assert plan.enabled is True
        assert plan.wire == WIRE_OPENAI_REASONING_EFFORT
        assert plan.kwargs_patch == {'reasoning_effort': 'medium'}

    def test_native_deepseek_reasoning_effort_when_catalog_supports_it(self):
        entry = lookup('deepseek/deepseek-v4-pro')
        assert entry is not None
        plan = resolve_reasoning_plan(entry, 'high')
        assert plan.enabled is True
        assert plan.wire == WIRE_OPENAI_REASONING_EFFORT
        assert plan.kwargs_patch == {'reasoning_effort': 'high'}

    def test_opencode_claude_adaptive_variant(self):
        entry = lookup('opencode/claude-fable-5')
        assert entry is not None
        plan = resolve_reasoning_plan(entry, 'low')
        assert plan.enabled is True
        assert plan.wire == WIRE_ANTHROPIC_ADAPTIVE
        assert plan.kwargs_patch['thinking'] == {
            'type': 'adaptive',
            'display': 'summarized',
        }
        assert plan.kwargs_patch['output_config'] == {'effort': 'low'}

    def test_none_disables_reasoning(self):
        entry = lookup('openai/gpt-5')
        assert entry is not None
        plan = resolve_reasoning_plan(entry, 'none')
        assert plan.enabled is False


class TestApplyModelParamOverridesIntegration:
    def test_opencode_deepseek_flash_free_sends_reasoning_effort(self):
        kwargs = {'model': 'opencode/deepseek-v4-flash-free', 'temperature': 0.5}
        out = apply_model_param_overrides(
            'opencode/deepseek-v4-flash-free',
            kwargs,
            reasoning_effort='medium',
        )
        assert 'thinking' not in out
        assert out['reasoning_effort'] == 'medium'

    def test_opencode_deepseek_flash_free_sanitizer_keeps_reasoning_effort(self):
        kwargs = {'model': 'opencode/deepseek-v4-flash-free', 'temperature': 0.5}
        out = apply_model_param_overrides(
            'opencode/deepseek-v4-flash-free',
            kwargs,
            reasoning_effort='max',
        )
        sanitized = sanitize_call_kwargs_for_provider(
            'opencode/deepseek-v4-flash-free',
            out,
        )
        assert 'thinking' not in sanitized
        assert sanitized['reasoning_effort'] == 'max'

    def test_gpt5_strips_temperature_when_catalog_requires(self):
        kwargs = {'model': 'openai/gpt-5', 'temperature': 0.5, 'max_tokens': 1000}
        out = apply_model_param_overrides(
            'openai/gpt-5',
            kwargs,
            reasoning_effort='high',
        )
        assert out['reasoning_effort'] == 'high'
        assert 'temperature' not in out
        assert out['max_completion_tokens'] == 1000

    def test_opencode_claude_messages_keeps_thinking_after_sanitize(self):
        kwargs = {'model': 'opencode/claude-fable-5', 'temperature': 0.0}
        out = apply_model_param_overrides(
            'opencode/claude-fable-5',
            kwargs,
            reasoning_effort='high',
        )
        sanitized = sanitize_call_kwargs_for_provider('opencode/claude-fable-5', out)
        assert sanitized['thinking']['type'] == 'adaptive'
        assert sanitized['output_config'] == {'effort': 'high'}
        assert 'reasoning_effort' not in sanitized

    @pytest.mark.parametrize(
        'effort',
        ['low', 'medium', 'high', 'max'],
    )
    def test_opencode_deepseek_effort_levels_from_variants(self, effort: str):
        entry = lookup('opencode/deepseek-v4-flash-free')
        assert entry is not None
        plan = resolve_reasoning_plan(entry, effort)
        assert plan.resolved_effort == effort


class TestApplyReasoningPlan:
    def test_merges_extra_body_for_gemini_openai_compat(self):
        call_kwargs: dict = {'model': 'x'}
        plan = resolve_reasoning_plan(
            _entry(
                name='gemini-3-flash',
                provider='opencode',
                inference_endpoint='/chat/completions',
                metadata={
                    'family': 'gemini-flash',
                    'capabilities': {'reasoning': True},
                },
            ),
            'medium',
        )
        apply_reasoning_plan(call_kwargs, plan)
        assert call_kwargs['reasoning_effort'] == 'medium'
        assert 'extra_body' in call_kwargs
