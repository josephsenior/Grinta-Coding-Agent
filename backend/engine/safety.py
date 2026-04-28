from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.contracts.state import State
    from backend.ledger.action import Action


class OrchestratorSafetyManager:
    """Passthrough safety manager.

    The previous regex-based hallucination detector produced false positives
    on conversational replies and has been removed.  This class is kept so
    call-sites in the executor and planner do not need to change.
    """

    def __init__(self, *args, **kwargs) -> None:
        _ = (args, kwargs)

    def should_enforce_tools(
        self,
        last_user_message: str | None,
        state: State,
        default: str,
    ) -> str:
        _ = (last_user_message, state)
        return default

    def apply(
        self, response_text: str, actions: list[Action]
    ) -> tuple[bool, list[Action]]:
        return True, actions
