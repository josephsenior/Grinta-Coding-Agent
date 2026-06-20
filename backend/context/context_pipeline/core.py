"""Split submodule — see package facade for public API."""

from __future__ import annotations

from backend.context.context_pipeline.core_base import _EmptyState
from backend.context.context_pipeline.core_prepare import ContextPipelinePrepareMixin
from backend.context.context_pipeline.core_prompt import ContextPipelinePromptMixin


class ContextPipeline(
    ContextPipelinePrepareMixin,
    ContextPipelinePromptMixin,
):
    """Fixed-order context pipeline replacing compactor strategy roulette."""


__all__ = ['ContextPipeline', '_EmptyState']
