"""Unit tests for param profiles and runtime profile resolution."""

from __future__ import annotations

from backend.inference.catalog_loader import lookup
from backend.inference.param_profiles import (
    resolve_effective_model_entry,
    resolve_model_entry_for_capabilities,
    resolve_param_profile_id,
    synthetic_entry_from_profile,
)
from backend.inference.reasoning import reasoning_effort_options
from backend.inference.runtime_profile import resolve_runtime_profile


def test_unknown_groq_model_uses_conservative_profile() -> None:
    profile_id, source = resolve_param_profile_id('some-new-groq-model', 'groq')
    assert profile_id == 'conservative'
    assert source == 'conservative'


def test_conservative_profile_strips_reasoning() -> None:
    entry = synthetic_entry_from_profile(
        'custom/model', 'custom', profile_id='conservative'
    )
    assert entry.strip_reasoning_effort is True
    assert entry.supports_reasoning_effort is False


def test_openai_gpt5_catalog_entry_keeps_runtime_overrides() -> None:
    entry, profile_id, source = resolve_effective_model_entry('openai/gpt-5', 'openai')
    assert entry is not None
    assert entry.use_max_completion_tokens is True
    assert profile_id == 'gpt-5'
    assert source == 'catalog'


def test_opencode_claude_fable_keeps_catalog_variants() -> None:
    raw = lookup('opencode/claude-fable-5')
    assert raw is not None
    entry = resolve_model_entry_for_capabilities('claude-fable-5', 'opencode', fallback=raw)
    assert entry is not None
    assert reasoning_effort_options(entry, include_disabled=True) == (
        'none',
        'low',
        'medium',
        'high',
        'xhigh',
        'max',
    )


def test_opencode_claude_haiku_uses_provider_scoped_catalog() -> None:
    raw = lookup('opencode/claude-haiku-4-5')
    assert raw is not None
    entry = resolve_model_entry_for_capabilities(
        'claude-haiku-4-5', 'opencode', fallback=raw
    )
    assert entry is not None
    assert entry.provider == 'opencode'
    assert reasoning_effort_options(entry, include_disabled=True) == (
        'none',
        'high',
        'max',
    )


def test_opencode_deepseek_flash_free_not_mapped_to_gemini_profile() -> None:
    raw = lookup('opencode/deepseek-v4-flash-free')
    assert raw is not None
    entry = resolve_model_entry_for_capabilities(
        'deepseek-v4-flash-free', 'opencode', fallback=raw
    )
    assert entry is not None
    assert reasoning_effort_options(entry, include_disabled=True) == (
        'none',
        'low',
        'medium',
        'high',
        'max',
    )


class _Cfg:
    model = 'groq/llama-3.3-70b-versatile'
    custom_llm_provider = 'groq'
    context_window_tokens = None
    max_output_tokens = None
    max_input_tokens = None


def test_runtime_profile_resolves_for_catalog_model() -> None:
    profile = resolve_runtime_profile(_Cfg())
    assert profile.param_profile_id == 'llama-3.3-70b-versatile'
    assert profile.source == 'catalog'
    assert profile.context_limits.usable_input_tokens is not None
