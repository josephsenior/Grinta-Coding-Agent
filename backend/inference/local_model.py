"""Shared helpers for detecting local / keyless LLM configurations."""

from __future__ import annotations

from typing import Any


def is_local_llm_config(llm_cfg: object) -> bool:
    """Return True when the configured model can run without a cloud API key."""
    from backend.inference.provider_resolver import get_resolver

    resolver = get_resolver()
    model = (getattr(llm_cfg, 'model', None) or '').strip()
    if model and resolver.is_local_model(model):
        return True

    provider = (
        getattr(llm_cfg, 'custom_llm_provider', None)
        or getattr(llm_cfg, 'provider', None)
        or ''
    )
    if str(provider).strip().lower() in {'ollama', 'lm_studio', 'vllm'}:
        return True

    base = (getattr(llm_cfg, 'base_url', None) or '').strip().lower()
    return any(host in base for host in ('localhost', '127.0.0.1', '0.0.0.0'))


def is_local_model_config(config: Any, resolver: Any | None = None) -> bool:
    """Return True when an LLM config object points at a local endpoint."""
    if resolver is None:
        from backend.inference.provider_resolver import get_resolver

        resolver = get_resolver()
    model = (getattr(config, 'model', None) or '').strip()
    if model and resolver.is_local_model(model):
        return True
    base = (getattr(config, 'base_url', None) or '').strip().lower()
    return any(host in base for host in ('localhost', '127.0.0.1', '0.0.0.0'))


__all__ = ['is_local_llm_config', 'is_local_model_config']
