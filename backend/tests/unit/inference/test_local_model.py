"""Tests for shared local-model detection."""

from __future__ import annotations

from types import SimpleNamespace

from backend.inference.local_model import is_local_llm_config, is_local_model_config


def test_is_local_llm_config_true_for_ollama_model() -> None:
    cfg = SimpleNamespace(model='ollama/llama3.2', provider='', base_url='')
    assert is_local_llm_config(cfg) is True


def test_is_local_llm_config_true_for_localhost_base_url() -> None:
    cfg = SimpleNamespace(
        model='custom/foo', provider='', base_url='http://127.0.0.1:11434'
    )
    assert is_local_llm_config(cfg) is True


def test_is_local_model_config_delegates_to_resolver() -> None:
    resolver = SimpleNamespace(is_local_model=lambda model: model.startswith('ollama/'))
    cfg = SimpleNamespace(model='ollama/test', base_url='')
    assert is_local_model_config(cfg, resolver) is True
