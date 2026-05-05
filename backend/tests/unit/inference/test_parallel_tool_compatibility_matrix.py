"""Parallel tool scheduling compatibility matrix (no live API calls).

Documents and guards Grinta's contract across providers:

* ``apply_model_param_overrides`` may set OpenAI-style ``parallel_tool_calls`` when
  ``catalog.json`` advertises ``supports_parallel_tool_calls``.
* ``sanitize_call_kwargs_for_provider`` strips that kwarg for **native** Google and
  Anthropic SDK routes (different wire protocols; Anthropic still supports parallel
  tool *use* via multiple ``tool_use`` blocks).
* ``_provider_parallel_tool_calls_supported`` (prompt builder) mirrors catalog only.
* ``_render_system_capabilities`` gates the user-facing ENABLED/DISABLED line.

If you change sanitization or catalog defaults, update this module alongside
``docs/`` or ``catalog.json``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from backend.engine.prompts.prompt_builder import (
    _provider_parallel_tool_calls_supported,
)
from backend.engine.prompts.section_renderers import _render_system_capabilities
from backend.inference.catalog_loader import (
    apply_model_param_overrides,
    sanitize_call_kwargs_for_provider,
)
from backend.inference.provider_resolver import KNOWN_PROVIDER_PREFIXES


def _base_kwargs() -> dict[str, Any]:
    return {'model': 'placeholder', 'temperature': 0.0}


@pytest.mark.parametrize(
    ('model', 'expect_parallel_kwarg_removed'),
    [
        pytest.param(
            'anthropic/claude-4.5-sonnet',
            True,
            id='anthropic_native_strip',
        ),
        pytest.param(
            'claude-4.5-sonnet',
            True,
            id='anthropic_catalog_name_strip',
        ),
        pytest.param(
            'google/gemini-2.5-flash',
            True,
            id='google_prefixed_strip',
        ),
        pytest.param(
            'gemini-2.5-flash',
            True,
            id='google_catalog_name_strip',
        ),
        pytest.param('gpt-4o', False, id='openai_catalog_keeps'),
        pytest.param('openai/gpt-4o', False, id='openai_alias_keeps'),
        pytest.param('lightning/kimi-k2.5', False, id='lightning_openai_compat_keeps'),
        pytest.param(
            'openrouter/meta-llama/llama-3.3-70b-versatile',
            False,
            id='openrouter_keeps',
        ),
        pytest.param('groq/llama-3.3-70b-versatile', False, id='groq_keeps'),
        pytest.param('ollama/qwen2.5', False, id='ollama_keeps'),
        pytest.param('xai/grok-3', False, id='xai_keeps'),
        pytest.param('deepseek/deepseek-chat', False, id='deepseek_keeps'),
        pytest.param('mistral/mistral-small-latest', False, id='mistral_keeps'),
        pytest.param('vllm/Qwen/Qwen2.5-7B-Instruct', False, id='vllm_keeps'),
        pytest.param('lm_studio/local-model', False, id='lm_studio_keeps'),
        pytest.param('nvidia/meta/llama-3.1-8b-instruct', False, id='nvidia_keeps'),
        pytest.param(
            'together/meta-llama/Llama-3.3-70B-Instruct-Turbo',
            False,
            id='together_keeps',
        ),
        pytest.param('kimi-k2.5', False, id='unknown_model_keeps'),
    ],
)
def test_sanitize_parallel_tool_calls_matrix(
    model: str,
    expect_parallel_kwarg_removed: bool,
) -> None:
    """``parallel_tool_calls`` is stripped only for native google / anthropic."""
    kwargs = {**_base_kwargs(), 'model': model, 'parallel_tool_calls': True}
    out = sanitize_call_kwargs_for_provider(model, kwargs)
    removed = 'parallel_tool_calls' not in out
    assert removed is expect_parallel_kwarg_removed


def test_all_known_prefixes_openai_compat_keep_parallel_kwarg() -> None:
    """Every non-google, non-anthropic known prefix keeps OpenAI-style kwargs."""
    for prefix in sorted(KNOWN_PROVIDER_PREFIXES - {'google', 'anthropic'}):
        model = f'{prefix}/test-model'
        kwargs = {**_base_kwargs(), 'model': model, 'parallel_tool_calls': True}
        out = sanitize_call_kwargs_for_provider(model, kwargs)
        assert out.get('parallel_tool_calls') is True, f'stripped for {model}'


def test_apply_overrides_sets_parallel_only_when_catalog_advertises() -> None:
    """Catalog ``supports_parallel_tool_calls`` drives apply_model_param_overrides."""
    gpt_kw = _base_kwargs()
    apply_model_param_overrides('gpt-4o', gpt_kw)
    assert gpt_kw.get('parallel_tool_calls') is True

    claude_kw = _base_kwargs()
    apply_model_param_overrides('claude-4.5-sonnet', claude_kw)
    assert claude_kw.get('parallel_tool_calls') is True

    unknown_kw = _base_kwargs()
    apply_model_param_overrides('totally-unknown-model-xyz', unknown_kw)
    assert 'parallel_tool_calls' not in unknown_kw


def test_apply_then_sanitize_openai_preserves_parallel_flag() -> None:
    """OpenAI catalog path: overrides add flag; sanitizer does not remove it."""
    kw = _base_kwargs()
    apply_model_param_overrides('gpt-4o', kw)
    out = sanitize_call_kwargs_for_provider('gpt-4o', kw)
    assert out.get('parallel_tool_calls') is True


def test_apply_then_sanitize_anthropic_drops_parallel_flag() -> None:
    """If parallel_tool_calls were present, Anthropic native sanitizer removes it."""
    kw = {**_base_kwargs(), 'parallel_tool_calls': True}
    apply_model_param_overrides('claude-4.5-sonnet', kw)
    # Catalog does not set parallel for Claude today; simulate upstream injection.
    kw['parallel_tool_calls'] = True
    out = sanitize_call_kwargs_for_provider('claude-4.5-sonnet', kw)
    assert 'parallel_tool_calls' not in out


@pytest.mark.parametrize(
    ('model_id', 'expected'),
    [
        pytest.param('gpt-4o', True, id='gpt4o_catalog_parallel'),
        pytest.param('openai/gpt-4o', True, id='gpt4o_alias_parallel'),
        pytest.param('claude-4.5-sonnet', True, id='claude_catalog_parallel'),
        pytest.param('kimi-k2.5', True, id='kimi_catalog_parallel'),
        pytest.param('lightning/foo', False, id='prefixed_unknown_no_catalog'),
    ],
)
def test_provider_parallel_tool_calls_supported_matrix(
    model_id: str,
    expected: bool,
) -> None:
    assert _provider_parallel_tool_calls_supported(model_id) is expected


@pytest.mark.parametrize(
    (
        'parallel_cfg',
        'provider_flag',
        'fc_mode',
        'expect_enabled_substring',
    ),
    [
        pytest.param(True, True, 'native', True, id='all_gates_on'),
        pytest.param(False, True, 'native', False, id='config_off'),
        pytest.param(True, False, 'native', False, id='provider_flag_off'),
        pytest.param(True, True, 'string', False, id='string_fc_mode'),
        pytest.param(True, True, 'unknown', False, id='unknown_fc_mode'),
    ],
)
def test_system_capabilities_parallel_scheduling_line_matrix(
    parallel_cfg: bool,
    provider_flag: bool,
    fc_mode: str,
    expect_enabled_substring: bool,
) -> None:
    cfg = SimpleNamespace(
        enable_parallel_tool_scheduling=parallel_cfg,
        enable_checkpoints=False,
        enable_lsp_query=False,
        enable_debugger=False,
    )
    text = _render_system_capabilities(
        cfg,
        function_calling_mode=fc_mode,
        multi_edit_available=False,
        parallel_tool_calls_provider_flag=provider_flag,
    )
    if expect_enabled_substring:
        assert 'ENABLED for read-only batches' in text
    else:
        assert 'DISABLED in this run' in text


def test_system_capabilities_parallel_native_all_on_renders_enabled() -> None:
    """Explicit happy path: ENABLED substring must appear."""
    cfg = SimpleNamespace(
        enable_parallel_tool_scheduling=True,
        enable_checkpoints=False,
        enable_lsp_query=False,
        enable_debugger=False,
    )
    text = _render_system_capabilities(
        cfg,
        function_calling_mode='native',
        multi_edit_available=False,
        parallel_tool_calls_provider_flag=True,
    )
    assert 'Parallel tool scheduling' in text
    assert 'ENABLED for read-only batches' in text
    assert 'read_file' in text and 'search_code' in text
