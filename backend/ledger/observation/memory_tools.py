"""Structured observations for checkpoint, working memory, and scratchpad tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from backend.core.enums import ObservationType
from backend.ledger.observation.observation import Observation


@dataclass
class CheckpointObservation(Observation):
    """Result of a checkpoint tool command."""

    content: str = ''
    command: str = ''
    ok: bool = True
    status: str = ''
    reason_code: str = ''
    reason: str = ''
    retryable: bool = False
    changed_state: bool = False
    next_best_action: str = ''
    data: dict[str, Any] = field(default_factory=dict)
    observation: ClassVar[str] = ObservationType.CHECKPOINT_RESULT

    @property
    def message(self) -> str:
        return self.content or self.reason or self.status


@dataclass
class WorkingMemoryObservation(Observation):
    """Result of a working-memory read or update."""

    content: str = ''
    command: str = ''
    section: str = 'all'
    updated_sections: list[str] = field(default_factory=list)
    memory_snapshot: dict[str, str] = field(default_factory=dict)
    ok: bool = True
    observation: ClassVar[str] = ObservationType.WORKING_MEMORY_RESULT

    @property
    def message(self) -> str:
        return self.content


@dataclass
class MemoryPersistObservation(Observation):
    """Result of persisting a workspace memory entry."""

    content: str = ''
    key: str = ''
    kind: str = ''
    inserted: bool = False
    observation: ClassVar[str] = ObservationType.MEMORY_PERSIST_RESULT

    @property
    def message(self) -> str:
        return self.content


@dataclass
class MemoryRecallObservation(Observation):
    """Result of semantic memory recall."""

    content: str = ''
    query: str = ''
    hits: list[dict[str, Any]] = field(default_factory=list)
    observation: ClassVar[str] = ObservationType.MEMORY_RECALL_RESULT

    @property
    def message(self) -> str:
        return self.content


@dataclass
class ScratchpadNoteObservation(Observation):
    """Result of storing a scratchpad note."""

    content: str = ''
    key: str = ''
    observation: ClassVar[str] = ObservationType.SCRATCHPAD_NOTE_RESULT

    @property
    def message(self) -> str:
        return self.content


@dataclass
class ScratchpadRecallObservation(Observation):
    """Result of recalling a scratchpad note."""

    content: str = ''
    key: str = ''
    value: str = ''
    found: bool = False
    observation: ClassVar[str] = ObservationType.SCRATCHPAD_RECALL_RESULT

    @property
    def message(self) -> str:
        return self.content
