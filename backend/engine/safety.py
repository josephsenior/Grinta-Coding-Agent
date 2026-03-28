from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.orchestration.state.state import State
    from backend.ledger.action import Action


class OrchestratorSafetyManager:
    """Deterministic safety manager.

    DEPRECATED: The legacy anti-hallucination layer was removed because structural
    function calling effectively mitigates hallucinations at the provider level. 
    This class now acts as a minimal safety shim, preserving orchestrator integration
    points so the architecture can introduce new safety constraints in the future.
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
