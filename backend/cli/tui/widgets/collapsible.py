"""Collapsible content widget for the Grinta TUI.

Provides expandable/collapsible sections for tool results, reasoning chains,
and other verbose content. Users can toggle visibility with keyboard shortcuts.
"""

from __future__ import annotations

from typing import Any
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal
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

    class DeleteRequested(Message):
        """Event fired when the row receives a delete intent."""
        def __init__(self, item_id: str | None) -> None:
            super().__init__()
            self.item_id = item_id

    def __init__(
        self,
        renderable: Any,
        item_id: str | None = None,
        *,
        deletable: bool = False,
        classes: str | None = None,
    ) -> None:
        super().__init__(renderable, classes=classes)
        self.item_id = item_id
        self.deletable = deletable

    def on_click(self, event: events.Click) -> None:
        if self.deletable:
            size = self.size.width or 0
            if size > 6 and event.x >= max(0, size - 4):
                self.post_message(self.DeleteRequested(self.item_id))
                event.prevent_default()
                event.stop()
                return
        self.post_message(self.Selected(self.item_id))
        event.prevent_default()
        event.stop()

    def on_key(self, event: events.Key) -> None:
        if event.key in ("enter", "space"):
            self.post_message(self.Selected(self.item_id))
            event.prevent_default()
            event.stop()
        elif event.key in ("delete", "backspace"):
            self.post_message(self.DeleteRequested(self.item_id))
            event.prevent_default()
            event.stop()


class CollapsibleSection(Container):
    class ActionClicked(Message):
        """Event fired when the action label is clicked."""
        
        def __init__(self, control: 'CollapsibleSection') -> None:
            super().__init__()
            self._control = control

        @property
        def control(self) -> 'CollapsibleSection':
            return self._control
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
    CollapsibleSection .collapsible-header-row {
        layout: horizontal;
        height: 1;
        width: 100%;
        margin-bottom: 1;
    }
    CollapsibleSection .collapsible-header {
        width: 1fr;
        height: 1;
        color: $text;
        text-style: bold;
    }
    CollapsibleSection .collapsible-action {
        width: auto;
        height: 1;
        color: #5eead4;
        text-style: bold;
        padding-right: 1;
    }
    CollapsibleSection .collapsible-action:hover {
        color: #ffffff;
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
    CollapsibleSection .thinking-content {
        color: lightgray;
        opacity: 0.7;
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
        action_label: str | None = None,
        id: str | None = None,
        is_thinking: bool = False,
    ) -> None:
        super().__init__(id=id)
        self._section_title = title
        self._content = content
        self._collapsed = collapsed
        self._accent_color = accent_color
        self._action_label = action_label
        self._items: list[tuple[Any, str, bool]] = []
        self._is_thinking = is_thinking

    @property
    def is_collapsed(self) -> bool:
        return self._collapsed

    def compose(self) -> ComposeResult:
        header_style = 'collapsed' if self._collapsed else 'expanded'
        icon = '▸' if self._collapsed else '▾'
        header_text = f'[{self._accent_color}]{icon}[/] {self._section_title}'
        
        with Horizontal(classes='collapsible-header-row', id='header-row'):
            yield Static(header_text, classes=f'collapsible-header {header_style}', id='header')
            if self._action_label:
                yield Static(self._action_label, classes='collapsible-action', id='action-btn')
                
        body_classes = (
            'collapsible-body -hidden' if self._collapsed else 'collapsible-body'
        )
        with Vertical(classes=body_classes, id='body'):
            if self._items:
                for renderable, item_id, deletable in self._items:
                    yield SidebarRow(renderable, item_id, deletable=deletable)
            else:
                content_classes = 'empty-text'
                if self._is_thinking:
                    content_classes += ' thinking-content'
                yield Static(self._content or '', id='empty-text', classes=content_classes)

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
        if event.widget and event.widget.id == 'action-btn':
            self.post_message(self.ActionClicked(self))
            event.prevent_default()
            event.stop()
            return

        if event.widget and (event.widget.id in ('header', 'header-row') or event.widget == self):
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

    def set_items(self, items: list[tuple[Any, str] | tuple[Any, str, bool]]) -> None:
        """Update the list of interactive items in the body."""
        normalized: list[tuple[Any, str, bool]] = []
        for item in items:
            if len(item) == 2:
                renderable, item_id = item
                normalized.append((renderable, item_id, False))
            else:
                renderable, item_id, deletable = item
                normalized.append((renderable, item_id, deletable))
        self._items = normalized
        body = self.query_one('#body', Vertical)
        body.remove_children()

        if normalized:
            for renderable, item_id, deletable in normalized:
                body.mount(SidebarRow(renderable, item_id, deletable=deletable))
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
