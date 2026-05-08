"""Event system for agent actions and observations.

Classes:
    ActionConfirmationStatus
    ActionSecurityRisk
    Action
"""

from __future__ import annotations

import dataclasses
import hashlib
import json

from dataclasses import dataclass, field
from typing import ClassVar

from backend._canonical import CanonicalMeta
from backend.core.enums import ActionSecurityRisk
from backend.core.schemas import (
    ActionConfirmationStatus,
)
from backend.ledger.event import Event


@dataclass
class Action(Event, metaclass=CanonicalMeta):
    """Base class for all agent actions.

    Actions represent things the agent wants to do (edit files, run commands, etc.).
    They are executed by the runtime and produce Observations.
    """

    action: ClassVar[str] = ''
    runnable: ClassVar[bool] = False
    __test__: ClassVar[bool] = False

    # Declared as a proper field so subclass __post_init__ chains are safe.
    confirmation_state: ActionConfirmationStatus = field(
        default=ActionConfirmationStatus.CONFIRMED, init=False
    )
    thought: str = field(default='', init=False)
    security_risk: ActionSecurityRisk = field(
        default=ActionSecurityRisk.LOW, init=False
    )
    idempotency_key: str = field(default='', init=False)

    @staticmethod
    def _compute_idempotency_key(action_obj: Action) -> str:
        """Deterministic SHA-256 of semantic fields (init=True, non-ClassVar)."""
        data: dict[str, object] = {}
        data['__type__'] = type(action_obj).__name__
        for f in dataclasses.fields(action_obj):
            if not f.init:
                continue
            try:
                data[f.name] = getattr(action_obj, f.name)
            except Exception:
                continue
        canonical = json.dumps(data, sort_keys=True, default=str, ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def __post_init__(self) -> None:
        # Ensure confirmation_state always has a value (idempotent with field default)
        if not hasattr(self, 'confirmation_state'):
            self.confirmation_state = ActionConfirmationStatus.CONFIRMED
        if not self.idempotency_key:
            self.idempotency_key = self._compute_idempotency_key(self)


__all__ = ['Action', 'ActionConfirmationStatus']
