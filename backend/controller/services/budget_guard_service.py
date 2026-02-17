"""Budget/bandwidth guard utilities for AgentController."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.logger import FORGE_logger as logger
from backend.events.observation.status import StatusObservation

if TYPE_CHECKING:
    from backend.controller.services.controller_context import ControllerContext

# Thresholds at which budget warnings are emitted (ascending order).
_BUDGET_THRESHOLDS: tuple[float, ...] = (0.50, 0.80, 0.90)


class BudgetGuardService:
    """Keeps budget control flags in sync with accumulated metrics.

    Additionally pushes real-time budget alerts through the event stream
    when cost crosses predefined thresholds (50 %, 80 %, 90 %).
    Each threshold fires at most once per session to avoid alert fatigue.
    """

    def __init__(self, context: ControllerContext) -> None:
        self._context = context
        # Track which thresholds have already been alerted so each fires once.
        self._alerted_thresholds: set[float] = set()

    def sync_with_metrics(self) -> None:
        """Update budget control flag and emit threshold alerts."""
        state_tracker = self._context.state_tracker
        if state_tracker and hasattr(state_tracker, "sync_budget_flag_with_metrics"):
            state_tracker.sync_budget_flag_with_metrics()

        self._check_budget_thresholds()

    # ------------------------------------------------------------------
    # Budget threshold alerts
    # ------------------------------------------------------------------

    def _check_budget_thresholds(self) -> None:
        """Emit a ``StatusObservation`` when cost crosses a new threshold."""
        state = self._context.state
        if state is None:
            return

        budget_flag = getattr(state, "budget_flag", None)
        if budget_flag is None:
            return

        try:
            current = float(budget_flag.current_value)
            max_value = float(budget_flag.max_value)
        except (AttributeError, TypeError, ValueError):
            return

        if max_value <= 0:
            return

        pct = current / max_value

        for threshold in _BUDGET_THRESHOLDS:
            if pct >= threshold and threshold not in self._alerted_thresholds:
                self._alerted_thresholds.add(threshold)
                self._emit_budget_alert(threshold, current, max_value, pct)

    def _emit_budget_alert(
        self,
        threshold: float,
        current: float,
        max_value: float,
        pct: float,
    ) -> None:
        """Push a budget-alert observation into the event stream."""
        from backend.events.event import EventSource

        level_pct = int(threshold * 100)
        content = (
            f"⚠️ Budget alert: {level_pct}% of ${max_value:.2f} budget used "
            f"(${current:.4f} spent, {pct * 100:.1f}% consumed)"
        )

        logger.warning(
            "Budget threshold %d%% crossed for session %s — $%.4f / $%.2f",
            level_pct,
            self._context.id,
            current,
            max_value,
            extra={"session_id": self._context.id},
        )

        # Use a lightweight status observation so the WebSocket pushes this
        # to all connected clients automatically via the event stream.
        try:
            obs = StatusObservation(
                content=content,
                status_type="budget_alert",
                extras={
                    "threshold": threshold,
                    "pct_used": round(pct, 4),
                    "current_cost": round(current, 4),
                    "max_budget": round(max_value, 2),
                },
            )
            self._context.emit_event(obs, EventSource.ENVIRONMENT)
        except Exception:
            logger.debug(
                "Failed to emit budget alert for session %s",
                self._context.id,
                exc_info=True,
            )
