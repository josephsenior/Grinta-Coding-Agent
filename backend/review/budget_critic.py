"""Critic that scores a run based on how much of the task budget was spent."""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from backend.review.base import BaseCritic, CriticResult

if TYPE_CHECKING:
    from backend.events import Event


def _extract_cost_from_events(events: Sequence[Event]) -> tuple[float, float]:
    """Return (accumulated_cost, max_budget) extracted from event metadata.

    Scans for the most recent event that carries ``metrics`` with
    ``accumulated_cost`` / ``max_budget_per_task`` fields (populated by the
    budget guard service).  Returns (0.0, 0.0) when no cost data is found.
    """
    for event in reversed(list(events)):
        metrics = getattr(event, "metrics", None) or getattr(event, "_metrics", None)
        if metrics is None:
            continue
        cost = getattr(metrics, "accumulated_cost", None)
        budget = getattr(metrics, "max_budget_per_task", None)
        if cost is not None and budget is not None:
            try:
                return float(cost), float(budget)
            except (TypeError, ValueError):
                continue
    return 0.0, 0.0


class BudgetCritic(BaseCritic):
    """Score a run based on how efficiently the task budget was used.

    If no budget is configured (max_budget == 0), the critic returns 1.0 —
    uncapped runs are not penalised.

    Scoring curve (lower spend relative to budget → higher score):
      spend < 50 %  → 1.0   (well within budget)
      50–80 %       → 0.8   (acceptable)
      80–100 %      → 0.5   (tight but finished)
      > 100 %       → 0.0   (over budget)

    You can also supply ``max_budget`` and ``actual_cost`` directly to the
    constructor for use outside of an event-based evaluation flow.
    """

    def __init__(
        self,
        max_budget: float = 0.0,
        actual_cost: float = 0.0,
    ) -> None:
        self.max_budget = max_budget
        self.actual_cost = actual_cost

    def evaluate(
        self, events: Sequence[Event], diff_patch: str | None = None
    ) -> CriticResult:
        cost = self.actual_cost
        budget = self.max_budget

        # If not pre-configured, try to read from event stream.
        if budget == 0.0:
            cost, budget = _extract_cost_from_events(events)

        if budget <= 0.0:
            return CriticResult(
                score=1.0,
                message="No budget cap configured; spending not penalised.",
            )

        pct = cost / budget

        if pct <= 0.50:
            score, label = 1.0, "well within budget"
        elif pct <= 0.80:
            score, label = 0.8, "acceptable usage"
        elif pct <= 1.00:
            score, label = 0.5, "tight but within budget"
        else:
            score, label = 0.0, "over budget"

        # Tweak: Only output a warning if we are within 10% of hitting the budget.
        if pct < 0.90:
            msg = ""
        else:
            msg = (
                f"⚠️ Budget Warning: ${cost:.4f} of ${budget:.2f} budget used "
                f"({pct * 100:.1f}%) — {label}."
            )
        return CriticResult(score=score, message=msg)
