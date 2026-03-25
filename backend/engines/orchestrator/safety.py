from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.controller.state.state import State
    from backend.events.action import Action


class OrchestratorSafetyManager:
    """Deterministic safety manager.

    The previous anti-hallucination layer was removed; this class now acts as a
    no-op safety shim that preserves the orchestrator integration points.
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

    def apply(self, response_text: str, actions: list[Action]) -> tuple[bool, list[Action]]:
        _ = response_text
        return True, actions
