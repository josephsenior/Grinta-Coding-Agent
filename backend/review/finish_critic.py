"""Rule-based critic for verifying that an agent run properly finished."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.events.action import Action, PlaybookFinishAction
from backend.review.base import BaseCritic, CriticResult

if TYPE_CHECKING:
    from backend.events import Event


class AgentFinishedCritic(BaseCritic):
    """This is a simple rule-based critic that checks if the last event is an PlaybookFinishAction.

    If not, it will return a score of 0 and a message indicating that the agent did not finish.
    If the git patch is provided and is empty, it will return a score of 0 and a message indicating that the git patch is empty.
    """

    def __init__(self) -> None:
        """Initialize the finish critic with no external dependencies."""

    def evaluate(self, events: list[Event], diff_patch: str | None = None) -> CriticResult:
        """Score run success by checking PlaybookFinishAction and optional git patch content."""
        last_action = next((h for h in reversed(events) if isinstance(h, Action)), None)
        if diff_patch is not None and len(diff_patch.strip()) == 0:
            return CriticResult(score=0, message="Git patch is empty.")
        if isinstance(last_action, PlaybookFinishAction):
            return CriticResult(score=1, message="Agent finished.")
        return CriticResult(score=0, message="Agent did not finish.")
