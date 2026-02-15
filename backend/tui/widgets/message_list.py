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
        background: $primary 15%;
        border-left: tall $primary;
    }
    .user-msg-label {
        color: $primary;
        text-style: bold;
    }
    .assistant-msg {
        margin: 1 6 0 0;
        padding: 0 1;
        background: $surface-lighten-1;
        border-left: tall $accent;
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
        container = Vertical(classes="user-msg")
        container.mount(Static("You", classes="user-msg-label"))
        container.mount(Static(content))
        self.mount(container)

    def add_assistant_message(self, content: str) -> None:
        container = Vertical(classes="assistant-msg")
        container.mount(Static("Forge", classes="assistant-msg-label"))
        container.mount(Static(content))
        self.mount(container)

    def add_system_message(self, content: str) -> None:
        self.mount(Static(content, classes="system-msg"))

    def add_action(self, title: str, body: str, thought: str = "") -> None:
        self.mount(ActionCard(title, body, thought))

    def add_observation(self, title: str, content: str) -> None:
        container = Vertical(classes="obs-card")
        container.mount(Static(f"◀ {title}", classes="obs-title"))
        if content:
            container.mount(Static(content))
        self.mount(container)
