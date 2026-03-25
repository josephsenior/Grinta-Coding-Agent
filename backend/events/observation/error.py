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

    ``notify_ui_only`` marks **user-facing LLM/provider/config** failures (bad API key,
    quota, provider outage messaging, etc.): the client shows a toast, hides the card
    from the transcript, and memory omits the observation from model context.

    Leave ``notify_ui_only`` false for **capability / tool** outcomes (MCP unreachable,
    command failed, file errors, etc.) so the agent still sees actionable feedback.
    """

    error_id: str = ""
    notify_ui_only: bool = False
    observation: ClassVar[str] = ObservationType.ERROR

    @property
    def message(self) -> str:
        """Get error message content."""
        return self.content

    def __str__(self) -> str:
        """Return a readable summary of the error message."""
        return f"**ErrorObservation**\n{self.content}"

