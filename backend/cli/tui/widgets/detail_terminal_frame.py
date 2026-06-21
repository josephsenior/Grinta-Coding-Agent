"""macOS-style terminal window chrome for shell/terminal detail screens."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static

from backend.cli.tui.screens.detail.helpers import traffic_lights_markup


class DetailTerminalFrame(Container):
    """Terminal pane with traffic-light header and scrollable body."""

    DEFAULT_CSS = """
    DetailTerminalFrame {
        width: 100%;
        height: auto;
        background: #060a14;
        border: solid #1b233a;
        margin: 0 0 1 0;
    }
    DetailTerminalFrame .terminal-chrome {
        width: 100%;
        height: 1;
        background: #111820;
        border-bottom: solid #1b233a;
        padding: 0 1;
        content-align: left middle;
    }
    DetailTerminalFrame .terminal-body {
        width: 100%;
        height: auto;
        padding: 0;
        background: #060a14;
    }
    DetailTerminalFrame .terminal-body .detail-syntax {
        width: 100%;
        height: auto;
        padding: 0;
        border: none;
        background: transparent;
    }
    DetailTerminalFrame .terminal-body .detail-code {
        width: 100%;
        height: auto;
        padding: 0;
        border: none;
        background: transparent;
    }
    """

    def __init__(
        self,
        *children: Any,
        title: str = '',
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._title = title
        self._children_widgets = list(children)

    def compose(self) -> ComposeResult:
        yield Static(
            traffic_lights_markup(self._title),
            classes='terminal-chrome',
            id='terminal-chrome',
        )
        with Container(classes='terminal-body'):
            for child in self._children_widgets:
                yield child
