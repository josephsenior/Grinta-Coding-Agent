"""Unit tests for param profiles and runtime profile resolution."""

from __future__ import annotations

from backend.inference.param_profiles import (
    resolve_effective_model_entry,
    resolve_param_profile_id,
    synthetic_entry_from_profile,
)
from backend.inference.runtime_profile import resolve_runtime_profile


def test_unknown_groq_model_uses_provider_default_profile() -> None:
    profile_id, source = resolve_param_profile_id('some-new-groq-model', 'groq')
    assert profile_id == 'provider_default'
    assert source == 'provider_default'


def test_conservative_profile_strips_reasoning() -> None:
    entry = synthetic_entry_from_profile('custom/model', 'custom', profile_id='conservative')
    assert entry.strip_reasoning_effort is True
    assert entry.supports_reasoning_effort is False


def test_openai_gpt5_catalog_entry_keeps_runtime_overrides() -> None:
    entry, profile_id, source = resolve_effective_model_entry('openai/gpt-5', 'openai')
    assert entry is not None
    assert entry.use_max_completion_tokens is True
    assert source in {'catalog', 'catalog_family', 'family'}


class _Cfg:
    model = 'groq/llama-3.3-70b-versatile'
    custom_llm_provider = 'groq'
    context_window_tokens = None
    max_output_tokens = None
    max_input_tokens = None


def test_runtime_profile_resolves_for_compat_model() -> None:
    profile = resolve_runtime_profile(_Cfg())
    assert profile.param_profile_id == 'provider_default'
    assert profile.context_limits.usable_input_tokens is not None
