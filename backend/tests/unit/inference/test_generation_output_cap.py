from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from backend.inference.capabilities.context_limits import (
    cap_generation_output_tokens,
    derive_usable_input_tokens,
)
from backend.inference.llm import LLM
from backend.inference.runtime_profile import resolve_runtime_profile


def test_generation_cap_preserves_smaller_model_limits() -> None:
    assert cap_generation_output_tokens(8_192) == 8_192
    assert cap_generation_output_tokens(32_000) == 32_000
    assert cap_generation_output_tokens(128_000) == 32_000


def test_generation_cap_does_not_change_context_budget_reservation() -> None:
    before = derive_usable_input_tokens(
        context_window_tokens=200_000,
        max_output_tokens=128_000,
    )

    assert before == 145_904
    assert cap_generation_output_tokens(128_000) == 32_000


def test_llm_exposes_32k_cap_but_runtime_profile_preserves_native_reservation() -> None:
    llm = LLM.__new__(LLM)
    llm.config = SimpleNamespace(
        model='test/capped-model',
        custom_llm_provider='test',
        context_window_tokens=200_000,
        max_input_tokens=None,
        max_output_tokens=None,
    )
    features = SimpleNamespace(
        context_window_tokens=200_000,
        max_input_tokens=145_904,
        max_output_tokens=128_000,
    )

    with patch('backend.inference.llm.get_features', return_value=features):
        llm.init_model_info()

    profile = resolve_runtime_profile(llm.config, provider='test')

    assert llm.config.max_output_tokens == 32_000
    assert llm.config._native_max_output_tokens_for_budget == 128_000
    assert profile.context_limits.max_output_tokens == 32_000
    assert profile.context_limits.usable_input_tokens == 145_904
