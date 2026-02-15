"""Shared model capability definitions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class ModelCapabilities:
    """Shared capability flags for LLM models."""

    supports_function_calling: bool = False
    supports_reasoning_effort: bool = False
    supports_prompt_cache: bool = False
    supports_stop_words: bool = True
    supports_response_schema: bool = False
