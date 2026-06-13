"""Tests for prompt cache hint eligibility and OpenAI message sanitization."""

from __future__ import annotations

from backend.inference.catalog_loader import apply_model_param_overrides, lookup
from backend.inference.mappers.openai import strip_prompt_cache_hints_from_messages
from backend.inference.prompt_caching import (
    model_supports_explicit_resource_cache,
    model_supports_prompt_cache_hints,
    model_uses_implicit_prompt_cache,
    prompt_cache_mode_for_model,
)

_CACHE_MESSAGE = [
    {
        'role': 'system',
        'content': [
            {
                'type': 'text',
                'text': 'hi',
                'cache_control': {'type': 'ephemeral'},
            }
        ],
        'cache_control': {'type': 'ephemeral'},
    }
]


def test_model_supports_hints_for_catalog_claude() -> None:
    assert model_supports_prompt_cache_hints('claude-sonnet-4-6')
    assert model_supports_prompt_cache_hints('anthropic/claude-sonnet-4-6')


def test_model_supports_hints_for_catalog_claude_haiku() -> None:
    assert model_supports_prompt_cache_hints('claude-haiku-4-5')
    assert model_supports_prompt_cache_hints('anthropic/claude-haiku-4-5')


def test_gemini_uses_explicit_resource_mode_not_hints() -> None:
    assert not model_supports_prompt_cache_hints('google/gemini-3-flash')
    assert not model_supports_prompt_cache_hints(
        'gemini-3-flash',
        provider='google',
    )
    assert model_supports_explicit_resource_cache(
        'gemini-3-flash',
        provider='google',
    )
    assert prompt_cache_mode_for_model('gemini-3-flash', provider='google') == (
        'explicit_resource'
    )


def test_model_supports_hints_for_vercel_gateway_claude() -> None:
    assert model_supports_prompt_cache_hints(
        'vercel/anthropic/claude-haiku-4.5',
    )
    assert model_supports_prompt_cache_hints(
        'anthropic/claude-haiku-4.5',
        provider='vercel',
    )


def test_model_supports_hints_false_for_uncataloged_ids() -> None:
    assert not model_supports_prompt_cache_hints('google/gemini-2.5-flash')
    assert not model_supports_prompt_cache_hints('gemini-2.5-pro')


def test_openai_gpt5_uses_implicit_cache_not_hints() -> None:
    assert not model_supports_prompt_cache_hints('gpt-4o')
    assert not model_supports_prompt_cache_hints('openai/gpt-5')
    assert model_uses_implicit_prompt_cache('gpt-5', provider='openai')
    assert prompt_cache_mode_for_model('gpt-5', provider='openai') == 'implicit'


def test_model_supports_hints_empty() -> None:
    assert not model_supports_prompt_cache_hints('')
    assert not model_supports_prompt_cache_hints('   ')


def test_apply_model_param_overrides_sets_prompt_cache_key_for_implicit() -> None:
    entry = lookup('gpt-5')
    assert entry is not None
    assert entry.prompt_cache_mode == 'implicit'

    out = apply_model_param_overrides(
        'gpt-5',
        {},
        provider='openai',
        caching_prompt=True,
    )
    assert out['prompt_cache_key'] == 'grinta:openai:gpt-5'

    disabled = apply_model_param_overrides(
        'gpt-5',
        {},
        provider='openai',
        caching_prompt=False,
    )
    assert 'prompt_cache_key' not in disabled


def test_strip_prompt_cache_hints_from_messages() -> None:
    messages = [dict(item) for item in _CACHE_MESSAGE]
    messages[0]['content'] = [dict(part) for part in messages[0]['content']]
    original_cc = messages[0]['cache_control']
    cleaned = strip_prompt_cache_hints_from_messages(
        messages,
        model='openai/gpt-5',
    )
    assert 'cache_control' not in cleaned[0]
    assert 'cache_control' not in cleaned[0]['content'][0]
    assert 'cache_control' in messages[0]
    assert original_cc == messages[0]['cache_control']


def test_strip_preserves_hints_for_cache_capable_gateway_model() -> None:
    cleaned = strip_prompt_cache_hints_from_messages(
        _CACHE_MESSAGE,
        model='anthropic/claude-haiku-4.5',
        provider='vercel',
    )
    assert cleaned[0]['cache_control'] == {'type': 'ephemeral'}
    assert cleaned[0]['content'][0]['cache_control'] == {'type': 'ephemeral'}
