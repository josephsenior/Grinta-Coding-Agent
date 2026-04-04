"""Lightweight status observation for system-level notifications.

Used for budget alerts, health warnings, and other non-agent status updates
that should be pushed to connected clients via WebSocket.
"""

from dataclasses import dataclass, field
from typing import Any, ClassVar

from backend.core.schemas import ObservationType
from backend.ledger.observation.observation import Observation


@dataclass
class StatusObservation(Observation):
    """A status notification pushed through the event stream.

    Unlike ``NullObservation`` (which is filtered out in the WebSocket layer),
    ``StatusObservation`` is forwarded to clients so they can display toasts
    or update UI indicators in real-time.

    Attributes:
        status_type: A machine-readable category (e.g. ``"budget_alert"``).
        extras: Arbitrary key-value metadata for the notification.
    """

    status_type: str = ''
    extras: dict[str, Any] = field(default_factory=dict)
    observation: ClassVar[str] = ObservationType.STATUS

    @property
    def message(self) -> str:
        """Human-readable status message."""
        return self.content
