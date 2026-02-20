"""Modal for viewing full command/output when truncated in chat."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class OutputModal(ModalScreen[None]):
    """Modal displaying full output (e.g. command stdout) when truncated in chat."""

    BINDINGS = [Binding("escape", "dismiss", "Close")]

    def __init__(self, title: str, content: str) -> None:
        super().__init__()
        self._title = title
        self._content = content

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(self._title, id="output-title")
            yield Static(self._content, id="output-content")
            yield Button("Close", variant="primary", id="output-close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "output-close":
            self.dismiss()
