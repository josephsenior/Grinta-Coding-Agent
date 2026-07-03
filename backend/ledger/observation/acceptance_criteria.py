"""Observation emitted after acceptance criteria operations."""

from dataclasses import dataclass, field
from typing import Any, ClassVar

from backend.core.schemas import ObservationType
from backend.ledger.observation.observation import Observation


@dataclass
class AcceptanceCriteriaObservation(Observation):
    """Result of an acceptance criteria operation."""

    command: str = ''
    criteria_list: list[dict[str, Any]] = field(default_factory=list)
    observation: ClassVar[str] = ObservationType.ACCEPTANCE_CRITERIA

    @property
    def message(self) -> str:
        """Get acceptance criteria operation result."""
        return self.content
