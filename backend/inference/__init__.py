"""Llm module public API."""

from __future__ import annotations

from typing import Any

__all__ = ['LLM']


def __getattr__(name: str) -> Any:
    if name == 'LLM':
        from backend.inference.llm import LLM

        return LLM
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
