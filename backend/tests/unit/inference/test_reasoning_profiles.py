"""Tests for catalog-backed reasoning effort resolution."""

from __future__ import annotations

from backend.inference.catalog_loader import ModelEntry, lookup
from backend.inference.capabilities.param_profiles import resolve_model_entry_for_capabilities
from backend.inference.reasoning import (
    WIRE_OPENAI_REASONING_EFFORT,
    infer_family,
    reasoning_effort_options,
    resolve_reasoning_plan,
)
from backend.inference.reasoning_profiles import (
    normalize_effort_value,
    resolve_allowed_efforts,
)


def _entry(name: str, provider: str, **kwargs) -> ModelEntry:
    return ModelEntry(name=name, provider=provider, **kwargs)


def test_catalog_claude_sonnet_has_explicit_efforts() -> None:
    entry = lookup('anthropic/claude-sonnet-4-6')
    assert entry is not None
    assert resolve_allowed_efforts(entry) == (
        'low',
        'medium',
        'high',
        'xhigh',
        'max',
    )


def test_explicit_runtime_reasoning_efforts_are_used() -> None:
    entry = _entry(
        name='gpt-5.9',
        provider='openai',
        supports_reasoning_effort=True,
        reasoning_efforts=('minimal', 'low', 'medium', 'high', 'xhigh'),
        reasoning_wire=WIRE_OPENAI_REASONING_EFFORT,
    )
    assert resolve_allowed_efforts(entry) == (
        'minimal',
        'low',
        'medium',
        'high',
        'xhigh',
    )
    assert reasoning_effort_options(entry, include_disabled=True) == (
        'none',
        'minimal',
        'low',
        'medium',
        'high',
        'xhigh',
    )


def test_native_anthropic_max_is_not_downgraded() -> None:
    entry = resolve_model_entry_for_capabilities('claude-opus-4-6', 'anthropic')
    assert entry is not None
    plan = resolve_reasoning_plan(entry, 'max')
    assert plan.resolved_effort == 'max'
    assert plan.kwargs_patch['thinking']['budget_tokens'] == 31999


def test_catalog_variants_still_override_family_profile() -> None:
    entry = lookup('opencode/claude-haiku-4-5')
    assert entry is not None
    assert reasoning_effort_options(entry, include_disabled=True) == (
        'none',
        'high',
        'max',
    )


def test_lightweight_reasoning_efforts_metadata_override() -> None:
    entry = _entry(
        name='custom-reasoner',
        provider='openai',
        supports_reasoning_effort=True,
        metadata={'reasoning_efforts': ['medium', 'high', 'xhigh']},
    )
    allowed = resolve_allowed_efforts(entry)
    assert allowed == ('medium', 'high', 'xhigh')


def test_normalize_effort_preserves_xhigh_when_allowed() -> None:
    allowed = ('low', 'medium', 'high', 'xhigh', 'max')
    assert normalize_effort_value('xhigh', allowed) == 'xhigh'
    assert normalize_effort_value('max', allowed) == 'max'


def test_openrouter_claude_uses_catalog_tiers() -> None:
    entry = resolve_model_entry_for_capabilities(
        'anthropic/claude-sonnet-4',
        'openrouter',
    )
    assert entry is not None
    options = reasoning_effort_options(entry, include_disabled=True)
    assert 'xhigh' in options
    assert 'max' in options
    assert 'minimal' not in options


def test_openrouter_gpt5_uses_explicit_catalog_efforts() -> None:
    entry = _entry(
        name='openai/gpt-5.4',
        provider='openrouter',
        supports_function_calling=True,
        supports_reasoning_effort=True,
        reasoning_efforts=('minimal', 'low', 'medium', 'high', 'xhigh'),
        reasoning_wire=WIRE_OPENAI_REASONING_EFFORT,
    )
    assert infer_family(entry) == 'gpt'
    allowed = resolve_allowed_efforts(entry)
    assert allowed == ('minimal', 'low', 'medium', 'high', 'xhigh')
