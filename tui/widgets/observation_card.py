"""Observation card — tool output with optional [View Output] for truncated content."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Static
from textual.containers import Vertical


class ObservationCard(Widget):
    """Card showing tool observation; [View Output] when content was truncated."""

    class ViewFullOutput(Message):
        """User requested full output. Bubbles to parent to open modal."""

        def __init__(self, title: str, content: str) -> None:
            super().__init__()
            self.title = title
            self.content = content

    DEFAULT_CSS = """
    ObservationCard {
        margin: 0 0 1 2;
        padding: 0 1;
        border: round $success 40%;
        height: auto;
    }
    .obs-title {
        color: $success;
        text-style: bold;
    }
    .obs-body {
        padding: 0 2;
    }
    .obs-view-btn {
        margin: 1 0 0 0;
        max-width: 16;
    }
    """

    def __init__(
        self,
        title: str,
        content: str,
        *,
        full_content: str | None = None,
    ) -> None:
        super().__init__()
        self._title = title
        self._display = content
        self._full = full_content if full_content and len(full_content) > len(content) else None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"◀ {self._title}", classes="obs-title")
            if self._display:
                yield Static(self._display, classes="obs-body")
            if self._full:
                yield Button("[View Output]", id="view-output", classes="obs-view-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "view-output" and self._full:
            self.post_message(self.ViewFullOutput(self._title, self._full))
