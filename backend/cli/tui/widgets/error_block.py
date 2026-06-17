"""Error transcript block — matches ThinkingIndicator / OrientLine chrome."""

from __future__ import annotations

from typing import Any

from rich.console import Group
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static

from backend.cli.theme import CLR_ERROR_BODY, CLR_ERROR_PIPE, CLR_ERROR_PREFIX


class ErrorBlock(Container):
    """Inline error row with left pipe — same layout as thinking/exploration blocks."""

    DEFAULT_CSS = """
    ErrorBlock {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
        border: transparent;
        background: #090d18;
        border-left: solid #5a2d2d;
        padding: 0 1 0 2;
    }
    ErrorBlock > #error-content {
        width: 100%;
        height: auto;
    }
    """

    def __init__(self, renderable: Any, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._renderable = renderable
        self.styles.border_left = ('solid', CLR_ERROR_PIPE)

    def compose(self) -> ComposeResult:
        yield Static(self._renderable, id='error-content')

    @staticmethod
    def simple_message(text: str) -> Text:
        """Single-line error with inline prefix."""
        return Text.assemble(
            ('Error: ', CLR_ERROR_PREFIX),
            (text, CLR_ERROR_BODY),
        )


def prefix_error_renderable(prefix: str, body: Any) -> Group:
    """Assemble prefix + body like ThinkingIndicator."""
    return Group(
        Text(f'{prefix}: ', style=CLR_ERROR_PREFIX),
        body,
    )
