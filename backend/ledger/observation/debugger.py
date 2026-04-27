"""Observation returned by Python debugger actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from backend.core.enums import ObservationType
from backend.ledger.observation.observation import Observation


@dataclass
class DebuggerObservation(Observation):
    """Structured observation for debugger tool results."""

    content: str
    session_id: str | None = None
    state: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    observation: ClassVar[str] = ObservationType.DEBUGGER

    @property
    def message(self) -> str:
        """Get the observation message."""
        target = f' ({self.session_id})' if self.session_id else ''
        return f'Debugger{target}: {self.state or "updated"}'
