"""Agent status bar — shows agent state, model name, and accumulated cost."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Label

# Map agent states to display indicators
_STATE_DISPLAY: dict[str, tuple[str, str]] = {
    "loading": ("⏳", "Initializing Workspace"),
    "running": ("⚡", "Agent Executing"),
    "awaiting_user_input": ("💡", "Ready for Guidance"),
    "awaiting_user_confirmation": ("✋", "Action Requires Approval"),
    "paused": ("⏸️", "Session Paused"),
    "stopped": ("🛑", "Session Terminated"),
    "finished": ("🚀", "Task Accomplished"),
    "rejected": ("⛔", "Task Rejected"),
    "error": ("💥", "System Error"),
    "rate_limited": ("🕐", "API Rate Limited"),
}


def _budget_color(ratio: float) -> str:
    """Return a Textual markup color for a cost/limit ratio (0–1+)."""
    if ratio >= 0.90:
        return "red"
    if ratio >= 0.80:
        return "dark_orange"
    if ratio >= 0.50:
        return "yellow"
    return "green"


class AgentStatusBar(Widget):
    """Persistent footer showing agent state, model, cost, and budget limits."""

    DEFAULT_CSS = """
    AgentStatusBar {
        height: 1;
        dock: bottom;
        background: $primary-darken-2;
        color: $text;
        padding: 0 1;
    }
    #state-label {
        width: auto;
        text-style: bold;
    }
    #model-label {
        width: 1fr;
        text-align: center;
        color: $text-muted;
    }
    #cost-label {
        width: auto;
        text-align: right;
    }
    #daily-label {
        width: auto;
        text-align: right;
        margin-left: 1;
        color: $text-muted;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._session_limit: float | None = None
        self._daily_limit: float | None = None
        self._daily_base: float = 0.0   # cost accumulated before this session

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label("⏳ Loading", id="state-label")
            yield Label("—", id="model-label")
            yield Label("$0.0000", id="cost-label")
            yield Label("", id="daily-label")

    def set_limits(
        self,
        session_limit: float | None,
        daily_limit: float | None,
        daily_base: float = 0.0,
    ) -> None:
        """Store budget limits so cost updates can be colour-coded.

        Args:
            session_limit: Max spend for this single session (USD), or None.
            daily_limit: Max spend across all sessions today (USD), or None.
            daily_base: Cost already accumulated today *before* this session.
        """
        self._session_limit = session_limit
        self._daily_limit = daily_limit
        self._daily_base = daily_base

    def update_state(self, state: str) -> None:
        icon, text = _STATE_DISPLAY.get(state, ("❓", state))
        self.query_one("#state-label", Label).update(f"{icon} {text}")

    def update_model(self, model: str) -> None:
        self.query_one("#model-label", Label).update(model)

    def update_cost(self, session_cost: float) -> None:
        """Refresh the cost labels with colour-coded budget indicators."""
        cost_label = self.query_one("#cost-label", Label)
        daily_label = self.query_one("#daily-label", Label)

        # ── Session cost ──────────────────────────────────────────
        if self._session_limit and self._session_limit > 0:
            ratio = session_cost / self._session_limit
            color = _budget_color(ratio)
            pct = min(ratio * 100, 999)
            cost_text = (
                f"[{color}]${session_cost:.4f}[/{color}]"
                f" / ${self._session_limit:.2f}"
                f"  [{color}]{pct:.0f}%[/{color}]"
            )
        else:
            cost_text = f"${session_cost:.4f}"

        cost_label.update(cost_text)

        # ── Daily cost ────────────────────────────────────────────
        if self._daily_limit and self._daily_limit > 0:
            today_total = self._daily_base + session_cost
            ratio = today_total / self._daily_limit
            color = _budget_color(ratio)
            daily_text = (
                f"[dim]day:[/dim] [{color}]${today_total:.4f}[/{color}]"
                f" / ${self._daily_limit:.2f}"
            )
            daily_label.update(daily_text)
        else:
            daily_label.update("")
