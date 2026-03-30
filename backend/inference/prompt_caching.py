"""Prompt-cache hint eligibility (provider-specific hints, not OpenAI auto-cache)."""

from __future__ import annotations

from backend.inference.catalog_loader import lookup
from backend.inference.model_features import PROMPT_CACHE_PATTERNS, model_matches


def model_supports_prompt_cache_hints(model: str) -> bool:
    """True if App may attach cache hints for this model.

    Catalog ``supports_prompt_cache`` is authoritative when present and true.
    Otherwise we fall back to :func:`get_features` pattern matching (e.g. uncatalogued
    Claude 3.x ids, DeepSeek, Gemini).
    """
    m = (model or "").strip()
    if not m:
        return False
    entry = lookup(m)
    if entry is not None and entry.supports_prompt_cache:
        return True
    return model_matches(m, PROMPT_CACHE_PATTERNS)
