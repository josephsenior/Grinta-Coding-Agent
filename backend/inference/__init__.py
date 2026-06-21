"""LLM inference public API."""

from __future__ import annotations

from typing import Any

__all__ = ['LLM']


def __getattr__(name: str) -> Any:
    if name == 'LLM':
        from backend.inference.llm import LLM

        return LLM
    import importlib

    aliases = {
        'catalog_loader': 'backend.inference.catalog.catalog_loader',
        'model_catalog': 'backend.inference.catalog.model_catalog',
        'registry': 'backend.inference.catalog.provider_catalog',
    }
    target = aliases.get(name)
    if target is not None:
        return importlib.import_module(target)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
