"""Confirmation bar widget — approve / reject agent actions."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Label


class ConfirmBar(Widget):
    """Docked bar that appears when the agent needs user confirmation.

    Emits :class:`Confirmed` or :class:`Rejected` messages.
    """

    DEFAULT_CSS = """
    ConfirmBar {
        height: auto;
        max-height: 4;
        dock: bottom;
        display: none;
        padding: 1 2;
        background: $warning 30%;
        border-top: heavy $warning;
        border-bottom: heavy $warning;
    }
    ConfirmBar.visible {
        display: block;
    }
    #confirm-label {
        width: 1fr;
        padding: 0 1;
        text-style: bold;
    }
    .confirm-btn {
        margin: 0 1;
        min-width: 12;
    }
    """

    class Confirmed(Message):
        """User approved the pending action."""

    class Rejected(Message):
        """User rejected the pending action."""

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label("Action requires confirmation", id="confirm-label")
            yield Button(
                "[Y] Allow", variant="success", id="btn-approve", classes="confirm-btn"
            )
            yield Button(
                "[N] Deny", variant="error", id="btn-reject", classes="confirm-btn"
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-approve":
            self.post_message(self.Confirmed())
        elif event.button.id == "btn-reject":
            self.post_message(self.Rejected())

    # ── public API ────────────────────────────────────────────────

    def show_confirmation(self, action_type: str, risk: str | None = None) -> None:
        """Display the bar with context about what needs confirming."""
        label = self.query_one("#confirm-label", Label)
        text = f"⚠ Confirm: {action_type}"
        if risk:
            text += f" (risk: {risk})"
        label.update(text)
        self.add_class("visible")

    def hide_confirmation(self) -> None:
        """Hide the confirmation bar."""
        self.remove_class("visible")
