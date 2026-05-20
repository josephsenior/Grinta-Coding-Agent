"""Collapsible content widget for the Grinta TUI.

Provides expandable/collapsible sections for tool results, reasoning chains,
and other verbose content. Users can toggle visibility with keyboard shortcuts.
"""

from __future__ import annotations

from typing import Any
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Static
from textual.message import Message


class SidebarRow(Static):
    """An interactive, hoverable, and focusable row inside sidebar panels."""

    can_focus = True

    class Selected(Message):
        """Event fired when the row is selected."""
        def __init__(self, item_id: str | None) -> None:
            super().__init__()
            self.item_id = item_id

    def __init__(
        self,
        renderable: Any,
        item_id: str | None = None,
        *,
        classes: str | None = None,
    ) -> None:
        super().__init__(renderable, classes=classes)
        self.item_id = item_id

    def on_click(self, event: events.Click) -> None:
        self.post_message(self.Selected(self.item_id))
        event.prevent_default()
        event.stop()

    def on_key(self, event: events.Key) -> None:
        if event.key in ("enter", "space"):
            self.post_message(self.Selected(self.item_id))
            event.prevent_default()
            event.stop()


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
        border: transparent;
    }
    CollapsibleSection:focus {
        border-left: solid $accent;
        background: #0d162a;
    }
    CollapsibleSection .collapsible-header {
        width: 100%;
        height: 1;
        color: $text;
        text-style: bold;
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

    can_focus = True

    BINDINGS = [
        ("enter", "toggle", "Toggle Expansion"),
        ("space", "toggle", "Toggle Expansion"),
    ]

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
        self._items: list[tuple[Any, str]] = []

    @property
    def is_collapsed(self) -> bool:
        return self._collapsed

    def compose(self) -> ComposeResult:
        header_style = 'collapsed' if self._collapsed else 'expanded'
        icon = '▸' if self._collapsed else '▾'
        header_text = f'[{self._accent_color}]{icon}[/] {self._section_title}'
        yield Static(
            header_text, classes=f'collapsible-header {header_style}', id='header'
        )
        body_classes = (
            'collapsible-body -hidden' if self._collapsed else 'collapsible-body'
        )
        with Vertical(classes=body_classes, id='body'):
            if self._items:
                for renderable, item_id in self._items:
                    yield SidebarRow(renderable, item_id)
            else:
                yield Static(self._content or '', id='empty-text')

    def toggle(self) -> None:
        """Toggle the collapsed state."""
        self._collapsed = not self._collapsed
        header = self.query_one('#header', Static)
        body = self.query_one('#body', Vertical)

        if self._collapsed:
            icon = '▸'
            header.classes = 'collapsible-header collapsed'
            body.add_class('-hidden')
        else:
            icon = '▾'
            header.classes = 'collapsible-header expanded'
            body.remove_class('-hidden')

        header_text = f'[{self._accent_color}]{icon}[/] {self._section_title}'
        header.update(header_text)

    def action_toggle(self) -> None:
        """Action handler for enter/space keypresses."""
        self.toggle()

    def on_click(self, event: events.Click) -> None:
        """Handle click events on the header or widget itself."""
        if event.widget and (event.widget.id == 'header' or event.widget == self):
            self.toggle()
            event.prevent_default()
            event.stop()

    def set_content(self, content: str) -> None:
        """Update the body content."""
        self._content = content
        self._items = []
        body = self.query_one('#body', Vertical)
        body.remove_children()
        body.mount(Static(content, id='empty-text'))

    def set_title(self, title: str) -> None:
        """Update the section title."""
        self._section_title = title
        header = self.query_one('#header', Static)
        icon = '▸' if self._collapsed else '▾'
        header_text = f'[{self._accent_color}]{icon}[/] {self._section_title}'
        header.update(header_text)

    def set_items(self, items: list[tuple[Any, str]]) -> None:
        """Update the list of interactive items in the body."""
        self._items = items
        body = self.query_one('#body', Vertical)
        body.remove_children()

        if items:
            for renderable, item_id in items:
                body.mount(SidebarRow(renderable, item_id))
        else:
            body.mount(Static(self._content or 'No items', id='empty-text'))

    def expand(self) -> None:
        """Expand the section."""
        if self._collapsed:
            self.toggle()

    def collapse(self) -> None:
        """Collapse the section."""
        if not self._collapsed:
            self.toggle()
