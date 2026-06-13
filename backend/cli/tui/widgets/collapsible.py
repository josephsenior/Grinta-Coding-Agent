"""Collapsible content widget for the Grinta TUI.

Provides expandable/collapsible sections for tool results, reasoning chains,
and other verbose content. Users can toggle visibility with keyboard shortcuts.
"""

from __future__ import annotations

from typing import Any

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.widgets import Static

STATUS_COLORS = {
    'ok': '#54efae',
    'err': '#fd8383',
    'warn': '#f6ff8f',
    'info': '#91abec',
    'neutral': '#969aad',
    'running': '#5eead4',
}

STATUS_ICONS = {
    'ok': '✓',
    'err': '✗',
    'warn': '!',
    'info': '?',
    'neutral': '•',
    'running': '…',
}


class SidebarRow(Static):
    """An interactive, hoverable, and focusable row inside sidebar panels.

    Renders in compact format: [status icon] [bold label] [muted meta]
    matching the ActivityCard collapsed-row visual language.
    """

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
        label: str,
        item_id: str | None = None,
        *,
        deletable: bool = False,
        status: str | None = None,
        meta: str | None = None,
        interactive: bool = True,
    ) -> None:
        self._label = label
        self._status = status or 'neutral'
        self._meta = meta
        self.interactive = interactive
        super().__init__(self._build_markup())
        self.item_id = item_id
        self.deletable = deletable
        self.can_focus = interactive
        if not interactive:
            self.add_class('-read-only')

    def _build_markup(self) -> str:
        color = STATUS_COLORS.get(self._status, '#969aad')
        icon = STATUS_ICONS.get(self._status, '•')
        icon_part = f'[{color}]{icon}[/]'
        label_part = f'[bold #c8d4e8]{self._label}[/]'
        meta_part = f'  [#54597b]{self._meta}[/]' if self._meta else ''
        return f'{icon_part} {label_part}{meta_part}'

    def update_status(self, status: str, meta: str | None = None) -> None:
        """Update the row status icon and optional meta text."""
        self._status = status
        if meta is not None:
            self._meta = meta
        self.update(self._build_markup())

    def on_click(self, event: events.Click) -> None:
        if not self.interactive:
            return
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
        if not self.interactive:
            return
        if event.key in ('enter', 'space'):
            self.post_message(self.Selected(self.item_id))
            event.prevent_default()
            event.stop()
        elif event.key in ('delete', 'backspace'):
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
    }
    CollapsibleSection .collapsible-header.collapsed {
        color: #6f83aa;
    }
    CollapsibleSection .collapsible-header.expanded {
        color: #c8d4e8;
        text-style: bold;
    }
    CollapsibleSection .collapsible-header-caret {
        width: auto;
        height: 1;
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
        ('enter', 'toggle', 'Toggle Expansion'),
        ('space', 'toggle', 'Toggle Expansion'),
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
        self._items: list[tuple[Any, str, bool, str | None, str | None, bool]] = []
        self._is_thinking = is_thinking

    @property
    def is_collapsed(self) -> bool:
        return self._collapsed

    def compose(self) -> ComposeResult:
        icon = '▸' if self._collapsed else '▾'
        caret = f'[#54597b]{icon}[/]'
        title_part = f'[{self._accent_color}]{self._section_title}[/]'
        header_text = f'{caret} {title_part}'

        with Horizontal(classes='collapsible-header-row', id='header-row'):
            yield Static(header_text, id='header')
            if self._action_label:
                yield Static(
                    self._action_label, classes='collapsible-action', id='action-btn'
                )

        body_classes = (
            'collapsible-body -hidden' if self._collapsed else 'collapsible-body'
        )
        with Vertical(classes=body_classes, id='body'):
            if self._items:
                for label, item_id, deletable, status, meta, interactive in self._items:
                    yield SidebarRow(
                        label,
                        item_id,
                        deletable=deletable,
                        status=status,
                        meta=meta,
                        interactive=interactive,
                    )
            else:
                content_classes = 'empty-text'
                if self._is_thinking:
                    content_classes += ' thinking-content'
                yield Static(
                    self._content or '', id='empty-text', classes=content_classes
                )

    def toggle(self) -> None:
        """Toggle the collapsed state."""
        self._collapsed = not self._collapsed
        header = self.query_one('#header', Static)
        body = self.query_one('#body', Vertical)

        icon = '▸' if self._collapsed else '▾'
        caret = f'[#54597b]{icon}[/]'
        header_text = f'{caret} [{self._accent_color}]{self._section_title}[/]'
        header.update(header_text)
        header.classes = (
            'collapsible-header collapsed'
            if self._collapsed
            else 'collapsible-header expanded'
        )

        if self._collapsed:
            body.add_class('-hidden')
        else:
            body.remove_class('-hidden')

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

        if event.widget and (
            event.widget.id in ('header', 'header-row') or event.widget == self
        ):
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
        caret = f'[#54597b]{icon}[/]'
        header_text = f'{caret} [{self._accent_color}]{title}[/]'
        header.update(header_text)

    def set_items(
        self,
        items: list[
            tuple[Any, str]
            | tuple[Any, str, bool]
            | tuple[Any, str, bool, str | None, str | None]
        ],
    ) -> None:
        """Update the list of interactive items in the body.

        Each item is a tuple of (label, item_id) or (label, item_id, deletable)
        or (label, item_id, deletable, status, meta)
        or (label, item_id, deletable, status, meta, interactive).
        """
        normalized: list[tuple[str, str, bool, str | None, str | None, bool]] = []
        for item in items:
            if len(item) >= 4:
                label, item_id, deletable, status = item[:4]
                meta = item[4] if len(item) >= 5 else None
                interactive = bool(item[5]) if len(item) >= 6 else True
                normalized.append(
                    (label, item_id, bool(deletable), status, meta, interactive)
                )
            elif len(item) == 3:
                label, item_id, deletable = item
                normalized.append((label, item_id, bool(deletable), None, None, True))
            else:
                label, item_id = item
                normalized.append((label, item_id, False, None, None, True))
        self._items = normalized
        body = self.query_one('#body', Vertical)
        body.remove_children()

        if normalized:
            for label, item_id, deletable, status, meta, interactive in normalized:
                body.mount(
                    SidebarRow(
                        label,
                        item_id,
                        deletable=deletable,
                        status=status,
                        meta=meta,
                        interactive=interactive,
                    )
                )
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
