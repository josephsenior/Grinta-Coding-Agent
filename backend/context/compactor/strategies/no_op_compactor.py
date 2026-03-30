"""Compactor implementation that simply returns the view unchanged."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.core.config.compactor_config import NoOpCompactorConfig
    from backend.inference.llm_registry import LLMRegistry

from backend.context.compactor.compactor import Compaction, Compactor
from backend.context.view import View


class NoOpCompactor(Compactor):
    """A compactor that does nothing to the event sequence."""

    def compact(self, view: View) -> View | Compaction:
        """Returns the list of events unchanged."""
        return view

    @classmethod
    def from_config(
        cls, config: Any, llm_registry: LLMRegistry
    ) -> NoOpCompactor:
        """Return a new no-op compactor regardless of configuration."""
        return NoOpCompactor()


# Lazy registration to avoid circular imports
def _register_config():
    """Register NoOpCompactorConfig with the NoOpCompactor factory.

    Defers import of NoOpCompactorConfig to avoid circular dependency between
    compactor implementations and their configuration classes. Called at module load time
    to enable from_config() factory method to instantiate compactors from config objects.

    Side Effects:
        - Imports NoOpCompactorConfig from backend.core.config.compactor_config
        - Registers config class with NoOpCompactor.register_config() factory

    Notes:
        - Must be called at module level after NoOpCompactor class definition
        - Pattern reused across all compactor implementations
        - Avoids import-time circular dependency that would occur if config imported at top level

    """
    from backend.core.config.compactor_config import NoOpCompactorConfig

    NoOpCompactor.register_config(NoOpCompactorConfig)


_register_config()
