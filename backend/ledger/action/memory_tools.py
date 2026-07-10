"""Action types for checkpoint, working memory, and scratchpad tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from backend.core.enums import ActionConfirmationStatus, ActionSecurityRisk, ActionType
from backend.ledger.action.action import Action


@dataclass
class CheckpointAction(Action):
    """Save, view, revert, or clear workspace checkpoints."""

    command: str = 'view'
    label: str = ''
    files_modified: str = ''
    checkpoint_id: str = ''

    action: ClassVar[str] = ActionType.CHECKPOINT
    runnable: ClassVar[bool] = True
    confirmation_state: ActionConfirmationStatus = ActionConfirmationStatus.CONFIRMED
    security_risk: ActionSecurityRisk = ActionSecurityRisk.LOW

    @property
    def message(self) -> str:
        return f'checkpoint {self.command}'


@dataclass
class WorkingMemoryAction(Action):
    """Read or update structured session working memory."""

    command: str = 'get'
    section: str = 'all'
    content: str = ''

    action: ClassVar[str] = ActionType.WORKING_MEMORY
    runnable: ClassVar[bool] = True
    confirmation_state: ActionConfirmationStatus = ActionConfirmationStatus.CONFIRMED
    security_risk: ActionSecurityRisk = ActionSecurityRisk.LOW

    @property
    def message(self) -> str:
        return f'working_memory {self.command} {self.section}'


@dataclass
class MemoryPersistAction(Action):
    """Persist a durable workspace-scoped memory entry."""

    key: str = ''
    value: str = ''
    kind: str = 'lesson'

    action: ClassVar[str] = ActionType.MEMORY_PERSIST
    runnable: ClassVar[bool] = True
    confirmation_state: ActionConfirmationStatus = ActionConfirmationStatus.CONFIRMED
    security_risk: ActionSecurityRisk = ActionSecurityRisk.LOW

    @property
    def message(self) -> str:
        return f'memory persist {self.key!r}'


@dataclass
class MemoryRecallAction(Action):
    """Semantic recall over indexed conversation history."""

    query: str = ''
    max_results: int = 8

    action: ClassVar[str] = ActionType.MEMORY_RECALL
    runnable: ClassVar[bool] = True
    confirmation_state: ActionConfirmationStatus = ActionConfirmationStatus.CONFIRMED
    security_risk: ActionSecurityRisk = ActionSecurityRisk.LOW

    @property
    def message(self) -> str:
        return f'search_history {self.query!r}'


@dataclass
class ScratchpadNoteAction(Action):
    """Store a key-value note in the session scratchpad."""

    key: str = ''
    value: str = ''

    action: ClassVar[str] = ActionType.SCRATCHPAD_NOTE
    runnable: ClassVar[bool] = True
    confirmation_state: ActionConfirmationStatus = ActionConfirmationStatus.CONFIRMED
    security_risk: ActionSecurityRisk = ActionSecurityRisk.LOW

    @property
    def message(self) -> str:
        return f'scratchpad note {self.key!r}'


@dataclass
class ScratchpadRecallAction(Action):
    """Recall a key from the session scratchpad."""

    key: str = ''

    action: ClassVar[str] = ActionType.SCRATCHPAD_RECALL
    runnable: ClassVar[bool] = True
    confirmation_state: ActionConfirmationStatus = ActionConfirmationStatus.CONFIRMED
    security_risk: ActionSecurityRisk = ActionSecurityRisk.LOW

    @property
    def message(self) -> str:
        return f'scratchpad recall {self.key!r}'
