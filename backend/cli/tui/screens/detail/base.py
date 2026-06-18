"""Base DetailScreen — shared chrome for all scan-line detail views."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static


class DetailScreen(Screen):
    """Reusable detail screen with header, scrollable body, and footer.

    Subclasses override :meth:`build_content` to return their widgets.
    Press ``escape`` to return to the feed.
    """

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def __init__(self, title: str = '') -> None:
        super().__init__()
        self._detail_title = title

    def build_content(self) -> list:
        """Return widgets to place in the scrollable body."""

    def compose(self) -> ComposeResult:
        title = Static(self._detail_title, id='detail-title')
        yield Header()
        yield title
        yield VerticalScroll(*self.build_content(), id='detail-body')
        yield Footer()

    DEFAULT_CSS = """
    DetailScreen {
        background: #060a14;
    }
    DetailScreen #detail-body {
        width: 100%;
        height: 1fr;
        padding: 0;
        scrollbar-size-vertical: 1;
        scrollbar-color: #334155 #060a14;
    }
    DetailScreen #detail-title {
        width: 100%;
        height: 1;
        padding: 0;
        content-align: left middle;
        background: #080c18;
        color: #91abec;
        border-bottom: solid #1e293b;
    }
    """
