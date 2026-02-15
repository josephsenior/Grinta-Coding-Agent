"""Condenser implementation that simply returns the view unchanged."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.config.condenser_config import NoOpCondenserConfig
    from backend.llm.llm_registry import LLMRegistry

from backend.memory.condenser.condenser import Condensation, Condenser
from backend.memory.view import View


class NoOpCondenser(Condenser):
    """A condenser that does nothing to the event sequence."""

    def condense(self, view: View) -> View | Condensation:
        """Returns the list of events unchanged."""
        return view

    @classmethod
    def from_config(cls, config: NoOpCondenserConfig, llm_registry: LLMRegistry) -> NoOpCondenser:
        """Return a new no-op condenser regardless of configuration."""
        return NoOpCondenser()


# Lazy registration to avoid circular imports
def _register_config():
    """Register NoOpCondenserConfig with the NoOpCondenser factory.

    Defers import of NoOpCondenserConfig to avoid circular dependency between
    condenser implementations and their configuration classes. Called at module load time
    to enable from_config() factory method to instantiate condensers from config objects.

    Side Effects:
        - Imports NoOpCondenserConfig from backend.core.config.condenser_config
        - Registers config class with NoOpCondenser.register_config() factory

    Notes:
        - Must be called at module level after NoOpCondenser class definition
        - Pattern reused across all condenser implementations
        - Avoids import-time circular dependency that would occur if config imported at top level

    """
    from backend.core.config.condenser_config import NoOpCondenserConfig

    NoOpCondenser.register_config(NoOpCondenserConfig)


_register_config()
