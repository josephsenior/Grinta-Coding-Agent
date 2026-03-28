"""Abstract plugin interfaces and requirement metadata for runtime extensions."""

from abc import abstractmethod
from dataclasses import dataclass

from backend.ledger.action import Action
from backend.ledger.observation import Observation


class Plugin:
    """Base class for a plugin.

    This will be initialized by the runtime client.
    """

    name: str

    @abstractmethod
    async def initialize(self, username: str) -> None:
        """Initialize the plugin."""

    @abstractmethod
    async def run(self, action: Action) -> Observation:
        """Run the plugin for a given action."""

    def get_init_bash_commands(self) -> list[str]:
        """Return a list of bash commands to run initialization."""
        return []

    async def shutdown(self) -> None:
        """Shutdown the plugin, releasing any held resources.

        Override in subclasses that allocate resources during
        ``initialize()`` or ``run()``.  The default is a no-op.
        """


@dataclass
class PluginRequirement:
    """Requirement for a plugin.

    Attributes:
        name: Unique plugin identifier.
        metadata_only: When ``True`` the plugin contributes documentation
            and prompt context but has **no** runtime ``run()`` behaviour.
            The orchestrator should never attempt to dispatch actions
            through a metadata-only plugin.
    """

    name: str
    metadata_only: bool = False
