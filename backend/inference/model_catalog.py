"""Model discovery helpers driven by the unified model catalog."""

from __future__ import annotations

from backend.core.config import AppConfig
from backend.inference.catalog_loader import (
    get_featured_models,
    get_model_options_by_provider,
)


def get_supported_llm_models(config: AppConfig | None = None) -> list[str]:
    """Get all models marked ``featured`` in catalog.json.

    Returns ``provider/name`` strings suitable for the API model picker.
    """
    return get_featured_models()


def get_supported_llm_models_by_provider(
    config: AppConfig | None = None,
) -> dict[str, list[str]]:
    """Return predefined exact model ids grouped by provider."""
    del config
    return get_model_options_by_provider()
