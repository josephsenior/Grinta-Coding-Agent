"""MessageDetailScreen — full agent message in a scrollable view."""

from __future__ import annotations

from textual.widgets import Static

from backend.cli.tui.screens.detail.base import DetailScreen


class MessageDetailScreen(DetailScreen):
    """Full agent message text, scrollable."""

    def __init__(self, message_text: str) -> None:
        super().__init__(title='Agent Message')
        self._message_text = message_text

    def build_content(self) -> list:
        from backend.cli.tui.renderer.prep import prep_markdown

        renderable = prep_markdown(self._message_text)
        if renderable is None:
            return [Static('(empty message)')]
        return [Static(renderable)]
