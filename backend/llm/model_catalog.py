"""Model discovery helpers driven by the unified model catalog."""

from __future__ import annotations

from backend.core.config import ForgeConfig
from backend.llm.catalog_loader import get_featured_models


def get_supported_llm_models(config: ForgeConfig | None = None) -> list[str]:
    """Get all models marked ``featured`` in catalog.toml.

    Returns ``provider/name`` strings suitable for the API model picker.
    """
    return get_featured_models()
