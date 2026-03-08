"""Observation emitted after updating the task tracking list."""

from dataclasses import dataclass, field
from typing import Any, ClassVar

from backend.core.schemas import ObservationType
from backend.events.observation.observation import Observation


@dataclass
class TaskTrackingObservation(Observation):
    """This data class represents the result of a task tracking operation."""

    command: str = ""
    task_list: list[dict[str, Any]] = field(default_factory=list)
    observation: ClassVar[str] = ObservationType.TASK_TRACKING

    @property
    def message(self) -> str:
        """Get task tracking operation result."""
        return self.content

