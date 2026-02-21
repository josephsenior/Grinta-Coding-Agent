"""Observation event models describing terminal outputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from backend.core.enums import ObservationType
from backend.events.observation.observation import Observation


@dataclass
class TerminalObservation(Observation):
    """Observation returned after interacting with a terminal session."""

    session_id: str
    content: str
    observation_type: ClassVar[str] = ObservationType.TERMINAL

    @property
    def message(self) -> str:
        """Get the observation message."""
        return f"Terminal ({self.session_id}) output updated."

    def __str__(self) -> str:
        """Return a readable summary."""
        return f"**TerminalObservation (session_id={self.session_id})**\nCONTENT:\n{self.content}"

    __test__ = False
