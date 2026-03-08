"""Observation types describing recoverable agent errors."""

from dataclasses import dataclass
from typing import ClassVar

from backend.core.schemas import ObservationType
from backend.events.observation.observation import Observation


@dataclass
class ErrorObservation(Observation):
    """This data class represents an error encountered by the agent.

    This is the type of error that LLM can recover from.
    E.g., Linter error after editing a file.
    """

    error_id: str = ""
    observation: ClassVar[str] = ObservationType.ERROR

    @property
    def message(self) -> str:
        """Get error message content."""
        return self.content

    def __str__(self) -> str:
        """Return a readable summary of the error message."""
        return f"**ErrorObservation**\n{self.content}"

