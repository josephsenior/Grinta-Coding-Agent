"""Observation payloads returned from Model Context Protocol calls."""

from dataclasses import dataclass, field
from typing import Any, ClassVar

from backend.core.schemas import ObservationType
from backend.events.observation.observation import Observation


@dataclass
class MCPObservation(Observation):
    """This data class represents the result of a MCP Server operation."""

    name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    observation: ClassVar[str] = ObservationType.MCP

    @property
    def message(self) -> str:
        """Get MCP operation result message."""
        return self.content

