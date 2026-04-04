"""Observation type for the signal_progress action."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from backend.core.enums import ObservationType
from backend.ledger.observation.observation import Observation


@dataclass
class SignalProgressObservation(Observation):
    """Acknowledgement that the controller received a progress signal.

    The controller resets the circuit-breaker stuck-detection counter (partially)
    when this observation is emitted.
    """

    acknowledged: bool = True
    content: str = ''
    observation_type: ClassVar[str] = ObservationType.SIGNAL_PROGRESS

    @property
    def message(self) -> str:
        return 'Progress signal acknowledged — stuck-detection counter reduced.'

    def __str__(self) -> str:
        return f'**SignalProgressObservation** acknowledged={self.acknowledged}\n{self.content}'
