from __future__ import annotations

from unittest.mock import patch

from backend.inference.model_catalog import get_supported_llm_models


def test_get_supported_llm_models_uses_featured_models() -> None:
    with patch(
        'backend.inference.model_catalog.get_featured_models',
        return_value=['openai/gpt-4.1', 'google/gemini-2.5-pro'],
    ) as mocked:
        models = get_supported_llm_models()

    assert models == ['openai/gpt-4.1', 'google/gemini-2.5-pro']
    mocked.assert_called_once()
