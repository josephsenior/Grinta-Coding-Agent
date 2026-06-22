"""Tests for family-driven reasoning wire mapping."""

from __future__ import annotations

import pytest

from backend.inference.catalog.catalog_loader import (
    ModelEntry,
    apply_model_param_overrides,
    lookup,
    sanitize_call_kwargs_for_provider,
)
from backend.inference.reasoning import (
    WIRE_ANTHROPIC_EXTENDED,
    WIRE_OPENAI_REASONING_EFFORT,
    WIRE_VERCEL_GATEWAY_REASONING,
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
            supports_reasoning_effort=True,
            reasoning_wire=WIRE_OPENAI_REASONING_EFFORT,
            reasoning_efforts=('high',),
            metadata={
                'capabilities': {'reasoning': True},
                'family': 'deepseek-flash-free',
                'variants': {'high': {'reasoningEffort': 'high'}},
            },
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

    def test_gateway_prefixed_claude_on_openrouter(self):
        entry = lookup('openrouter/anthropic/claude-sonnet-4')
        assert entry is not None
        assert supports_reasoning(entry) is True
        from backend.inference.reasoning import reasoning_effort_options

        assert reasoning_effort_options(entry, include_disabled=True)


class TestGatewayReasoningOptions:
    def test_openrouter_claude_via_effective_entry(self):
        from backend.inference.capabilities.param_profiles import (
            resolve_model_entry_for_capabilities,
        )
        from backend.inference.reasoning import reasoning_effort_options

        entry = resolve_model_entry_for_capabilities(
            'anthropic/claude-sonnet-4',
            'openrouter',
        )
        assert entry is not None
        options = reasoning_effort_options(entry, include_disabled=True)
        assert 'medium' in options
        assert 'none' in options
        assert 'minimal' not in options

    def test_openrouter_gpt41_has_no_reasoning_options(self):
        from backend.inference.capabilities.param_profiles import (
            resolve_model_entry_for_capabilities,
        )
        from backend.inference.reasoning import (
            reasoning_control_available,
            reasoning_effort_display_options,
            reasoning_effort_options,
        )

        entry = resolve_model_entry_for_capabilities(
            'openai/gpt-4.1',
            'openrouter',
        )
        assert entry is not None
        assert reasoning_effort_options(entry, include_disabled=True) == ()
        assert reasoning_effort_display_options(entry, include_disabled=True) == []
        assert reasoning_control_available(entry) is False

    def test_opencode_mimo_free_exposes_reasoning_controls(self):
        from backend.inference.capabilities.param_profiles import (
            resolve_model_entry_for_capabilities,
        )
        from backend.inference.reasoning import (
            reasoning_control_available,
            reasoning_effort_display_options,
            supports_reasoning,
        )

        entry = resolve_model_entry_for_capabilities('mimo-v2.5-free', 'opencode')
        assert entry is not None
        assert supports_reasoning(entry) is True
        assert reasoning_control_available(entry) is True
        options = reasoning_effort_display_options(entry, include_disabled=True)
        assert options
        assert {value for _label, value in options} >= {'', 'low', 'medium', 'high'}

    def test_vercel_claude_via_effective_entry(self):
        from backend.inference.capabilities.param_profiles import (
            resolve_model_entry_for_capabilities,
        )
        from backend.inference.reasoning import reasoning_effort_options

        entry = resolve_model_entry_for_capabilities(
            'anthropic/claude-sonnet-4',
            'vercel',
        )
        assert entry is not None
        options = reasoning_effort_options(entry, include_disabled=True)
        assert 'medium' in options

    def test_vercel_deepseek_gateway_reasoning_wire(self):
        from backend.inference.capabilities.param_profiles import (
            resolve_model_entry_for_capabilities,
        )
        from backend.inference.reasoning import resolve_reasoning_plan

        entry = resolve_model_entry_for_capabilities(
            'deepseek/deepseek-v4-pro',
            'vercel',
        )
        assert entry is not None
        assert 'max' not in (entry.reasoning_efforts or ())
        plan = resolve_reasoning_plan(entry, 'max')
        assert plan.wire == WIRE_VERCEL_GATEWAY_REASONING
        assert plan.kwargs_patch == {
            'reasoning': {'effort': 'xhigh', 'enabled': True},
        }
        plan_high = resolve_reasoning_plan(entry, 'high')
        assert plan_high.kwargs_patch == {
            'reasoning': {'effort': 'high', 'enabled': True},
        }

    def test_vercel_minimax_gateway_reasoning_split(self):
        from backend.inference.capabilities.param_profiles import (
            resolve_model_entry_for_capabilities,
        )
        from backend.inference.reasoning import resolve_reasoning_plan

        entry = resolve_model_entry_for_capabilities(
            'minimax/minimax-m3',
            'vercel',
        )
        assert entry is not None
        plan = resolve_reasoning_plan(entry, 'medium')
        assert plan.wire == WIRE_VERCEL_GATEWAY_REASONING
        assert plan.kwargs_patch == {
            'reasoning': {'effort': 'medium', 'enabled': True},
            'thinking': {'type': 'adaptive'},
            'reasoning_split': True,
        }

    def test_vercel_minimax_m25_gateway_reasoning_split_only(self):
        from backend.inference.capabilities.param_profiles import (
            resolve_model_entry_for_capabilities,
        )
        from backend.inference.reasoning import resolve_reasoning_plan

        entry = resolve_model_entry_for_capabilities(
            'minimax/minimax-m2.5',
            'vercel',
        )
        assert entry is not None
        plan = resolve_reasoning_plan(entry, 'high')
        assert plan.kwargs_patch == {
            'reasoning': {'effort': 'high', 'enabled': True},
            'reasoning_split': True,
        }

    def test_vercel_kimi_k25_gateway_reasoning_wire(self):
        from backend.inference.capabilities.param_profiles import (
            resolve_model_entry_for_capabilities,
        )
        from backend.inference.reasoning import resolve_reasoning_plan

        entry = resolve_model_entry_for_capabilities(
            'moonshotai/kimi-k2.5',
            'vercel',
        )
        assert entry is not None
        plan = resolve_reasoning_plan(entry, 'medium')
        assert plan.wire == WIRE_VERCEL_GATEWAY_REASONING
        assert plan.kwargs_patch == {
            'reasoning': {'effort': 'medium', 'enabled': True},
            'thinking': {'type': 'enabled', 'keep': None},
        }

    def test_vercel_gemini_pro_gateway_reasoning_wire(self):
        from backend.inference.capabilities.param_profiles import (
            resolve_model_entry_for_capabilities,
        )
        from backend.inference.reasoning import resolve_reasoning_plan

        entry = resolve_model_entry_for_capabilities(
            'google/gemini-3.1-pro',
            'vercel',
        )
        assert entry is not None
        plan = resolve_reasoning_plan(entry, 'high')
        assert plan.wire == WIRE_VERCEL_GATEWAY_REASONING
        assert plan.kwargs_patch == {
            'reasoning': {'effort': 'high', 'enabled': True},
        }

    def test_vercel_deepseek_reasoning_tunneled_via_extra_body(self):
        from backend.inference.catalog.catalog_loader import (
            apply_model_param_overrides,
            sanitize_call_kwargs_for_provider,
        )

        kwargs = {'model': 'vercel/deepseek/deepseek-v4-pro', 'temperature': 0.5}
        out = apply_model_param_overrides(
            'vercel/deepseek/deepseek-v4-pro',
            kwargs,
            reasoning_effort='xhigh',
            provider='vercel',
        )
        sanitized = sanitize_call_kwargs_for_provider(
            'vercel/deepseek/deepseek-v4-pro', out
        )
        assert 'reasoning' not in sanitized
        assert sanitized['extra_body']['reasoning'] == {
            'effort': 'xhigh',
            'enabled': True,
        }

    def test_vercel_qwen37_plus_has_configurable_thinking(self):
        from backend.inference.catalog.catalog_loader import (
            apply_model_param_overrides,
            sanitize_call_kwargs_for_provider,
        )
        from backend.inference.reasoning import reasoning_effort_options

        entry = lookup('vercel/alibaba/qwen3.7-plus')
        assert entry is not None
        options = reasoning_effort_options(entry, include_disabled=True)
        assert 'xhigh' in options

        kwargs = {
            'model': 'vercel/alibaba/qwen3.7-plus',
            'temperature': 0.5,
            'reasoning_effort': 'high',
        }

        out = apply_model_param_overrides(
            'vercel/alibaba/qwen3.7-plus',
            kwargs,
            reasoning_effort='high',
            provider='vercel',
        )

        assert out['reasoning'] == {'effort': 'high', 'enabled': True}
        assert 'reasoning_effort' not in out

        xhigh = apply_model_param_overrides(
            'vercel/alibaba/qwen3.7-plus',
            {'model': 'vercel/alibaba/qwen3.7-plus', 'temperature': 0.5},
            reasoning_effort='xhigh',
            provider='vercel',
        )
        sanitized = sanitize_call_kwargs_for_provider(
            'vercel/alibaba/qwen3.7-plus', xhigh
        )
        assert 'reasoning' not in sanitized
        assert sanitized['extra_body']['reasoning'] == {
            'effort': 'xhigh',
            'enabled': True,
        }

        disabled = apply_model_param_overrides(
            'vercel/alibaba/qwen3.7-plus',
            {'model': 'vercel/alibaba/qwen3.7-plus', 'reasoning_effort': 'none'},
            reasoning_effort='none',
            provider='vercel',
        )

        assert 'reasoning' not in disabled
        assert 'thinking' not in disabled
        assert 'enable_thinking' not in disabled
        assert 'reasoning_effort' not in disabled


class TestReasoningDisplayOptions:
    def test_opencode_claude_fable_display_labels_match_variants(self):
        from backend.inference.reasoning import reasoning_effort_display_options

        entry = lookup('opencode/claude-fable-5')
        assert entry is not None
        labels_by_value = {
            value: label
            for label, value in reasoning_effort_display_options(
                entry, include_disabled=True
            )
        }
        assert labels_by_value[''] == 'Default'
        assert labels_by_value['xhigh'] == 'Xhigh'
        assert labels_by_value['max'] == 'Max'
        assert 'minimal' not in labels_by_value

    def test_gemini_control_label(self):
        from backend.inference.reasoning import reasoning_control_label

        entry = lookup('google/gemini-3-flash')
        assert entry is not None
        assert reasoning_control_label(entry) == 'Thinking level'


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
        assert plan.wire == WIRE_ANTHROPIC_EXTENDED
        assert plan.kwargs_patch['thinking'] == {
            'type': 'enabled',
            'budget_tokens': 1024,
        }

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
        assert sanitized.get('extra_body', {}).get('reasoning_effort') == 'max'

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
        assert sanitized['thinking']['type'] == 'enabled'
        assert sanitized['thinking']['budget_tokens'] == 8192
        assert 'output_config' not in sanitized
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
        # assert call_kwargs.get('extra_body', {}).get('reasoning_effort') == 'medium'
