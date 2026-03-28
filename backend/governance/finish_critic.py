"""Rule-based critic for verifying that an agent run properly finished."""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from backend.ledger.action import Action, PlaybookFinishAction
from backend.governance.base import BaseCritic, CriticResult

if TYPE_CHECKING:
    from backend.ledger import Event


class AgentFinishedCritic(BaseCritic):
    """This is a simple rule-based critic that checks if the last event is an PlaybookFinishAction.

    If not, it will return a score of 0 and a message indicating that the agent did not finish.
    If the git patch is provided and is empty, it will return a score of 0 and a message indicating that the git patch is empty.
    """

    def __init__(self) -> None:
        """Initialize the finish critic with no external dependencies."""

    def evaluate(
        self, events: Sequence[Event], diff_patch: str | None = None
    ) -> CriticResult:
        """Score run success by checking PlaybookFinishAction and optional git patch content."""
        last_action = next((h for h in reversed(events) if isinstance(h, Action)), None)
        if diff_patch is not None and len(diff_patch.strip()) == 0:
            return CriticResult(score=0, message="❌ Task Incomplete: Verification failed. The agent claimed to be finished but generated no code changes.")
        if isinstance(last_action, PlaybookFinishAction):
            return CriticResult(score=1, message="✅ Task Complete: Agent successfully resolved the objective.")
        return CriticResult(score=0, message="❌ Task Incomplete: Agent stopped without a clear resolution.")
