"""Placeholder action used when no operation is required."""

from dataclasses import dataclass, field
from typing import ClassVar

from backend.core.schemas import ActionType
from backend.ledger.action.action import Action


class NullActionReason:
    """Source-tagging constants for NullAction instances.

    Use these to distinguish legitimate sentinel no-ops from NullActions that
    originate from an LLM producing no output. The latter should be counted
    toward the consecutive-null-action circuit breaker; the former should not.
    """

    SENTINEL = 'sentinel'
    """Legitimate placeholder: bootstrap init or orphaned-observation pairing."""

    FALLBACK_EMPTY = 'fallback_empty_response'
    """LLM produced no tool calls and no text — now raises LLMNoActionError
    instead of becoming a NullAction, but this constant is preserved for
    any direct NullAction construction that represents a genuine empty-response
    fallback (e.g. in tests or future edge cases)."""


@dataclass
class NullAction(Action):
    """An action that does nothing.

    The ``reason`` field should be set to a :class:`NullActionReason` constant
    whenever the origin of the no-op matters for circuit-breaker logic.
    Instances with ``reason == NullActionReason.SENTINEL`` are skipped by the
    consecutive-null-action counter in :class:`ActionExecutionService`.
    """

    action: ClassVar[str] = ActionType.NULL

    reason: str = field(default='')
    """Origin hint — use :class:`NullActionReason` constants."""

    @property
    def message(self) -> str:
        """Get null action message."""
        return 'No action'
