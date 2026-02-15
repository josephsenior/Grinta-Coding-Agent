"""Abstract interfaces for pluggable settings store implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.config.forge_config import ForgeConfig
    from backend.storage.data_models.settings import Settings


class SettingsStore(ABC):
    """Abstract base class for storing user settings.

    This is an extension point in Forge that allows applications to customize how
    user settings are stored. Applications can substitute their own implementation by:
    1. Creating a class that inherits from SettingsStore
    2. Implementing all required methods
    3. Setting server_config.settings_store_class to the fully qualified name of the class

    The class is instantiated via get_impl() in forge.server.shared.py.

    The implementation may or may not support multiple users depending on the environment.
    """

    @abstractmethod
    async def load(self) -> Settings | None:
        """Load session init data."""

    @abstractmethod
    async def store(self, settings: Settings) -> None:
        """Store session init data."""

    @classmethod
    @abstractmethod
    async def get_instance(
        cls, config: ForgeConfig, user_id: str | None
    ) -> SettingsStore:
        """Get a store for the user represented by the token given."""
