"""Observation emitted by the canonical task-state service."""
from dataclasses import dataclass, field
from typing import Any, ClassVar
from backend.core.schemas import ObservationType
from backend.ledger.observation.observation import Observation

@dataclass
class TaskStateObservation(Observation):
    command: str = ''
    revision: int = 0
    state: dict[str, Any] = field(default_factory=dict)
    observation: ClassVar[str] = ObservationType.TASK_STATE
