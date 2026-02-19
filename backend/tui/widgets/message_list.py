"""Message list widget — scrollable container of chat messages and action cards."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Static

from backend.tui.widgets.action_card import ActionCard


class MessageList(Widget):
    """Vertically stacked list of messages, actions, and observations.

    New items are appended to the bottom.  The parent ``VerticalScroll``
    handles scrolling.
    """

    DEFAULT_CSS = """
    MessageList {
        height: auto;
        min-height: 4;
    }
    .user-msg {
        margin: 1 0 0 6;
        padding: 0 1;
        background: $primary 10%;
        border-left: tall $primary 40%;
    }
    .user-msg-label {
        color: $primary;
        text-style: bold;
    }
    .assistant-msg {
        margin: 1 6 0 0;
        padding: 0 1;
        background: #080808;
        border-left: tall $accent 40%;
    }
    .assistant-msg-label {
        color: $accent;
        text-style: bold;
    }
    .system-msg {
        margin: 1 2;
        padding: 0 1;
        color: $text-muted;
        text-style: italic;
        text-align: center;
    }
    .obs-card {
        margin: 0 0 0 4;
        padding: 0 1;
        border: round $success;
        height: auto;
    }
    .obs-title {
        color: $success;
        text-style: bold;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("Welcome to Forge TUI", classes="system-msg")

    # ── public API ────────────────────────────────────────────────

    def add_user_message(self, content: str) -> None:
        """Append a user message bubble."""
        container = Vertical(
            Static("You", classes="user-msg-label"),
            Static(content),
            classes="user-msg",
        )
        self.mount(container)

    def add_assistant_message(self, content: str) -> None:
        """Append an assistant message bubble."""
        container = Vertical(
            Static("Forge", classes="assistant-msg-label"),
            Static(content),
            classes="assistant-msg",
        )
        self.mount(container)

    def add_system_message(self, content: str) -> None:
        """Append a centred system/info message."""
        self.mount(Static(content, classes="system-msg"))

    def add_action(self, title: str, body: str, thought: str = "") -> None:
        """Append an action card requiring user approval."""
        self.mount(ActionCard(title, body, thought))

    def add_observation(self, title: str, content: str) -> None:
        """Append a tool-observation card."""
        children: list[Static] = [Static(f"◀ {title}", classes="obs-title")]
        if content:
            children.append(Static(content))
        container = Vertical(*children, classes="obs-card")
        self.mount(container)
