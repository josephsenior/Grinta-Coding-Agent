"""Collapsible content widget for the Grinta TUI.

Provides expandable/collapsible sections for tool results, reasoning chains,
and other verbose content. Users can toggle visibility with keyboard shortcuts.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static


class CollapsibleSection(Container):
    """A collapsible section with a header and expandable body.

    Usage::

        yield CollapsibleSection(
            title="Shell Command",
            content=rich_renderable,
            collapsed=True,  # start collapsed
            accent_color="#91abec",
        )
    """

    DEFAULT_CSS = """
    CollapsibleSection {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
    }
    CollapsibleSection .collapsible-header {
        width: 100%;
        height: 1;
        color: $text;
    }
    CollapsibleSection .collapsible-header.collapsed {
        color: $text-muted;
    }
    CollapsibleSection .collapsible-header.expanded {
        color: $text-primary;
    }
    CollapsibleSection .collapsible-body {
        width: 100%;
        height: auto;
        margin-left: 2;
    }
    CollapsibleSection .collapsible-body.-hidden {
        display: none;
    }
    """

    def __init__(
        self,
        title: str,
        content: str | None = None,
        *,
        collapsed: bool = True,
        accent_color: str = '#91abec',
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._section_title = title
        self._content = content
        self._collapsed = collapsed
        self._accent_color = accent_color

    @property
    def is_collapsed(self) -> bool:
        return self._collapsed

    def compose(self) -> ComposeResult:
        header_style = 'collapsed' if self._collapsed else 'expanded'
        icon = '[bold]+[/]' if self._collapsed else '[bold]−[/]'
        header_text = f'[{self._accent_color}]{icon}[/] {self._section_title}'
        yield Static(header_text, classes=f'collapsible-header {header_style}', id='header')
        body_classes = 'collapsible-body -hidden' if self._collapsed else 'collapsible-body'
        yield Static(self._content or '', classes=body_classes, id='body')

    def toggle(self) -> None:
        """Toggle the collapsed state."""
        self._collapsed = not self._collapsed
        header = self.query_one('#header', Static)
        body = self.query_one('#body', Static)

        if self._collapsed:
            icon = '[bold]+[/]'
            header.classes = 'collapsible-header collapsed'
            body.add_class('-hidden')
        else:
            icon = '[bold]−[/]'
            header.classes = 'collapsible-header expanded'
            body.remove_class('-hidden')

        header_text = f'[{self._accent_color}]{icon}[/] {self._section_title}'
        header.update(header_text)

    def set_content(self, content: str) -> None:
        """Update the body content."""
        self._content = content
        body = self.query_one('#body', Static)
        body.update(content)

    def expand(self) -> None:
        """Expand the section."""
        if self._collapsed:
            self.toggle()

    def collapse(self) -> None:
        """Collapse the section."""
        if not self._collapsed:
            self.toggle()
