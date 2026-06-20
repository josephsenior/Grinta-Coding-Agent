"""Vision capability checks for TUI image paste and send."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.inference.catalog.catalog_loader import model_supports_vision

if TYPE_CHECKING:
    from backend.core.config.llm_config import LLMConfig


def image_input_blocked_reason(llm_config: LLMConfig | object | None) -> str | None:
    """Return a user-facing error message when image input is not allowed."""
    if llm_config is None:
        return (
            'Image input is unavailable until the agent is ready. '
            'Try again in a moment.'
        )

    model = getattr(llm_config, 'model', None) or ''

    if getattr(llm_config, 'disable_vision', None) is True:
        return (
            'Image input is disabled. Open /settings and enable vision '
            '(set disable_vision to false in your LLM config).'
        )

    if not model_supports_vision(model):
        return (
            'This model does not support image input. '
            'Select a vision-capable model in /settings.'
        )

    return None
