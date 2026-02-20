"""Action card widget — collapsible display of agent actions (commands, edits, etc.)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static


class ActionCard(Widget):
    """Compact card showing an agent action (file edit, command, MCP call, etc.).

    Displays the action type and a brief summary.
    """

    DEFAULT_CSS = """
    ActionCard {
        margin: 1 0;
        padding: 0 1;
        border: round $warning;
        height: auto;
    }
    .action-title {
        color: $warning;
        text-style: bold;
    }
    .action-thought {
        color: $text-muted;
        text-style: italic;
    }
    .action-body {
        padding: 0 2;
    }
    """

    def __init__(self, title: str, body: str, thought: str = "") -> None:
        super().__init__()
        self._title = title
        self._body = body
        self._thought = thought

    def compose(self) -> ComposeResult:
        yield Static(f"▶ {self._title}", classes="action-title")
        if self._thought:
            yield Static(self._thought, classes="action-thought")
        if self._body:
            yield Static(self._body, classes="action-body")
