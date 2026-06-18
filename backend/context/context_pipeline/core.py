"""Split submodule — see package facade for public API."""

from __future__ import annotations

from backend.context.context_pipeline.core_base import (
    ContextPipelineBaseMixin,
    _EmptyState,
)
from backend.context.context_pipeline.core_compact import ContextPipelineCompactionMixin
from backend.context.context_pipeline.core_gates import ContextPipelineGatesMixin
from backend.context.context_pipeline.core_prepare import ContextPipelinePrepareMixin
from backend.context.context_pipeline.core_prompt import ContextPipelinePromptMixin
from backend.context.context_pipeline.core_state import ContextPipelineStateMixin


class ContextPipeline(
    ContextPipelinePrepareMixin,
    ContextPipelinePromptMixin,
    ContextPipelineCompactionMixin,
    ContextPipelineStateMixin,
    ContextPipelineGatesMixin,
    ContextPipelineBaseMixin,
):
    """Fixed-order context pipeline replacing compactor strategy roulette."""


__all__ = ['ContextPipeline', '_EmptyState']
