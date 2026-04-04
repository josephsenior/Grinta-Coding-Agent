"""Strategies for compacting long conversation histories into summaries."""

# Import implementations to trigger compactor registrations.
from backend.context.compactor import strategies  # noqa: F401
from backend.context.compactor.compactor import (
    COMPACTOR_REGISTRY,
    BaseLLMCompactor,
    Compaction,
    Compactor,
    RollingCompactor,
    get_compaction_metadata,
)
from backend.context.view import View

__all__ = [
    'BaseLLMCompactor',
    'COMPACTOR_REGISTRY',
    'Compaction',
    'Compactor',
    'get_compaction_metadata',
    'RollingCompactor',
    'View',
]
