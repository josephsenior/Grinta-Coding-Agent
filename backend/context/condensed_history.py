"""Result type for history condensation steps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.ledger.action import Action
    from backend.ledger.event import Event


@dataclass
class CondensedHistory:
    events: list[Event]
    pending_action: Action | None


__all__ = ['CondensedHistory']
