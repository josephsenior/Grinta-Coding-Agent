"""Unified model catalog loader.

Reads ``catalog.toml`` once and exposes typed helpers consumed by
``cost_tracker``, ``model_features``, ``model_catalog``, and ``constants``.

Adding a new model requires editing **only** ``catalog.toml`` — no Python
changes needed.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Sequence

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

_CATALOG_PATH = Path(__file__).with_name("catalog.toml")


@dataclass(frozen=True, slots=True)
class ModelEntry:
    """A single model's metadata from the catalog."""

    name: str
    provider: str
    aliases: tuple[str, ...] = ()
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    input_price_per_m: float | None = None
    output_price_per_m: float | None = None
    verified: bool = False
    featured: bool = False
    supports_function_calling: bool = False
    supports_reasoning_effort: bool = False
    supports_prompt_cache: bool = False
    supports_stop_words: bool = True
    supports_response_schema: bool = False
    supports_vision: bool = False


@functools.lru_cache(maxsize=1)
def _load_raw() -> dict:
    """Load and cache the raw TOML data."""
    with open(_CATALOG_PATH, "rb") as f:
        return tomllib.load(f)


@functools.lru_cache(maxsize=1)
def get_catalog() -> tuple[ModelEntry, ...]:
    """Return all model entries from ``catalog.toml``."""
    data = _load_raw()
    entries: list[ModelEntry] = []
    for name, info in data.get("models", {}).items():
        entries.append(
            ModelEntry(
                name=name,
                provider=info["provider"],
                aliases=tuple(info.get("aliases", ())),
                max_input_tokens=info.get("max_input_tokens"),
                max_output_tokens=info.get("max_output_tokens"),
                input_price_per_m=info.get("input_price_per_m"),
                output_price_per_m=info.get("output_price_per_m"),
                verified=info.get("verified", False),
                featured=info.get("featured", False),
                supports_function_calling=info.get("supports_function_calling", False),
                supports_reasoning_effort=info.get("supports_reasoning_effort", False),
                supports_prompt_cache=info.get("supports_prompt_cache", False),
                supports_stop_words=info.get("supports_stop_words", True),
                supports_response_schema=info.get("supports_response_schema", False),
                supports_vision=info.get("supports_vision", False),
            )
        )
    return tuple(entries)


@functools.lru_cache(maxsize=1)
def _name_index() -> dict[str, ModelEntry]:
    """Build a lookup dict: canonical name and all aliases → ModelEntry."""
    idx: dict[str, ModelEntry] = {}
    for entry in get_catalog():
        idx[entry.name] = entry
        for alias in entry.aliases:
            idx[alias] = entry
    return idx


def lookup(model: str) -> ModelEntry | None:
    """Look up a model by name or alias (case-insensitive, strips provider prefix)."""
    idx = _name_index()
    key = model.strip()
    # Try exact
    entry = idx.get(key) or idx.get(key.lower())
    if entry:
        return entry
    # Strip provider prefix (e.g. "openai/gpt-4o" → "gpt-4o")
    if "/" in key:
        bare = key.split("/")[-1]
        entry = idx.get(bare) or idx.get(bare.lower())
        if entry:
            return entry
    return None


def get_pricing(model: str) -> dict[str, float] | None:
    """Get pricing for a model, with tier fallback.

    Returns ``{"input": <per_1M>, "output": <per_1M>}`` or ``None``.
    """
    entry = lookup(model)
    if entry and entry.input_price_per_m is not None:
        return {
            "input": entry.input_price_per_m,
            "output": entry.output_price_per_m or 0.0,
        }

    # Tier fallback — substring matching
    data = _load_raw()
    tier = data.get("tier_pricing", {})
    bare = model.split("/")[-1].lower() if "/" in model else model.lower()
    for prefix, prices in tier.items():
        if prefix in bare:
            return {"input": prices["input"], "output": prices["output"]}
    return None


def get_token_limits(model: str) -> tuple[int | None, int | None]:
    """Return ``(max_input_tokens, max_output_tokens)`` for *model*."""
    entry = lookup(model)
    if entry:
        return entry.max_input_tokens, entry.max_output_tokens
    return None, None


def get_featured_models() -> list[str]:
    """Return ``provider/name`` strings for models marked ``featured = true``."""
    return [f"{e.provider}/{e.name}" for e in get_catalog() if e.featured]


def get_verified_models(provider: str | None = None) -> list[str]:
    """Return canonical names for models marked ``verified = true``.

    If *provider* is given, filter to that provider only.
    """
    return [
        e.name
        for e in get_catalog()
        if e.verified and (provider is None or e.provider == provider)
    ]


def get_all_model_names() -> Sequence[str]:
    """Return all known canonical model names."""
    return [e.name for e in get_catalog()]


def is_openai_compatible(model: str) -> bool:
    """Check if a model uses OpenAI-compatible API.

    Returns:
        True if model should use OpenAI client
    """
    entry = lookup(model)
    if entry:
        # These providers are OpenAI-compatible
        return entry.provider in ["openai", "deepseek", "mistral", "xai"]

    # Heuristic fallback
    model_lower = model.lower()
    return any(
        x in model_lower
        for x in ["gpt-", "o1-", "o3-", "o4-", "codex", "deepseek", "grok", "mistral"]
    )


def get_provider_info(model: str) -> dict[str, Any]:
    """Get provider information for a model.

    Returns:
        Dictionary with provider metadata
    """
    entry = lookup(model)
    if entry:
        return {
            "provider": entry.provider,
            "supports_function_calling": entry.supports_function_calling,
            "supports_vision": entry.supports_vision,
            "supports_prompt_cache": entry.supports_prompt_cache,
            "max_input_tokens": entry.max_input_tokens,
            "max_output_tokens": entry.max_output_tokens,
        }

    # Return defaults for unknown models
    return {
        "provider": "openai",
        "supports_function_calling": False,
        "supports_vision": False,
        "supports_prompt_cache": False,
        "max_input_tokens": None,
        "max_output_tokens": None,
    }
