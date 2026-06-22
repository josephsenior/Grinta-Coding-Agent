"""Collapsible content widget for the Grinta TUI.

Provides expandable/collapsible sections for tool results, reasoning chains,
and other verbose content. Users can toggle visibility with keyboard shortcuts.
"""

from __future__ import annotations

from typing import Any

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Static, Switch

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

SIDEBAR_BULLET = '●'
SIDEBAR_BULLET_DIM = '○'


class SidebarRow(Static):
    """An interactive, hoverable, and focusable row inside sidebar panels."""

    can_focus = True

    class Selected(Message):
        """Event fired when the row is selected (Enter / click)."""

        def __init__(self, item_id: str | None) -> None:
            super().__init__()
            self.item_id = item_id

    class DeleteRequested(Message):
        """Event fired when the row receives a delete intent."""

        def __init__(self, item_id: str | None) -> None:
            super().__init__()
            self.item_id = item_id

    class ToggleRequested(Message):
        """Event fired when a toggleable row should flip enabled state."""

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
        toggleable: bool = False,
        disabled: bool = False,
        view_only: bool = False,
    ) -> None:
        self._label = label
        self._status = status or 'neutral'
        self._meta = meta
        self.interactive = interactive
        self.item_id = item_id
        self.deletable = deletable
        self.toggleable = toggleable
        self._disabled = disabled
        self.view_only = view_only
        self._show_delete_hint = False
        super().__init__(self._build_markup(), classes='sidebar-item-row')
        self.can_focus = interactive
        if view_only:
            self.add_class('-view-only')
        if disabled:
            self.add_class('-disabled')
        if not interactive:
            self.add_class('-read-only')

    def _bullet_color(self) -> str:
        if self._disabled:
            return '#54597b'
        if self.view_only:
            return '#8b95a8'
        if not self.interactive:
            return '#8b95a8'
        return STATUS_COLORS.get(self._status, '#969aad')

    def _bullet_glyph(self) -> str:
        if self._disabled or self.view_only:
            return SIDEBAR_BULLET_DIM
        return SIDEBAR_BULLET

    def _build_markup(self) -> str:
        color = self._bullet_color()
        bullet_part = f'[{color}]{self._bullet_glyph()}[/]'
        if self._disabled:
            label_part = f'[#54597b][strike]{self._label}[/][/]'
        elif self.view_only:
            label_part = f'[#8b95a8]{self._label}[/]'
        else:
            label_part = f'[#c8d4e8]{self._label}[/]'
        meta_part = f'  [#54597b]{self._meta}[/]' if self._meta else ''
        return f'{bullet_part} {label_part}{meta_part}'

    def _refresh_row_markup(self) -> None:
        self.update(self._build_markup())

    def set_disabled(self, disabled: bool) -> None:
        self._disabled = disabled
        if disabled:
            self.add_class('-disabled')
        else:
            self.remove_class('-disabled')
        self._refresh_row_markup()

    def update_status(self, status: str, meta: str | None = None) -> None:
        """Update the row status icon and optional meta text."""
        self._status = status
        if meta is not None:
            self._meta = meta
        self.update(self._build_markup())

    def on_click(self, event: events.Click) -> None:
        if not self.interactive:
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
        elif self.deletable and event.key in ('delete', 'backspace'):
            self.post_message(self.DeleteRequested(self.item_id))
            event.prevent_default()
            event.stop()


class McpServerRow(Horizontal):
    """MCP server row: read-only label with a compact enable switch on the right."""

    DEFAULT_CSS = """
    McpServerRow {
        width: 100%;
        height: auto;
        min-height: 1;
        align: left middle;
        margin: 0 0 1 0;
        padding: 0 1;
        background: transparent;
    }
    McpServerRow:hover {
        background: #101c36;
    }
    McpServerRow:focus-within {
        background: #0e1a30;
        border-left: solid #eacb8a;
    }
    McpServerRow.-highlight {
        background: #132a45;
        border-left: solid #eacb8a;
    }
    McpServerRow .sidebar-row-label {
        width: 1fr;
        height: 1;
        content-align: left middle;
        padding: 0;
    }
    McpServerRow Switch {
        width: 4;
        height: 1;
        min-height: 1;
        margin: 0 0 0 1;
        border: none;
        background: transparent;
        padding: 0;
    }
    McpServerRow Switch .switch--slider {
        background: #0f1c30;
        color: #54597b;
    }
    McpServerRow Switch.-on .switch--slider {
        background: #15274d;
        color: #5eead4;
    }
    McpServerRow Switch:focus {
        border: none;
    }
    """

    def __init__(
        self,
        label: str,
        item_id: str | None,
        *,
        enabled: bool = True,
    ) -> None:
        super().__init__(classes='sidebar-item-row')
        self.item_id = item_id
        self._label = label
        self._enabled = enabled
        self._suppress_switch = False
        if not enabled:
            self.add_class('-disabled')

    def _label_markup(self) -> str:
        if self._enabled:
            bullet = f'[{STATUS_COLORS["ok"]}]{SIDEBAR_BULLET}[/]'
            label_part = f'[#c8d4e8]{self._label}[/]'
        else:
            bullet = f'[#54597b]{SIDEBAR_BULLET_DIM}[/]'
            label_part = f'[#54597b][strike]{self._label}[/][/]'
        return f'{bullet} {label_part}'

    def compose(self) -> ComposeResult:
        yield Static(self._label_markup(), classes='sidebar-row-label', id='row-label')
        yield Switch(value=self._enabled, id='mcp-enable-switch')

    def on_mount(self) -> None:
        self._suppress_switch = True
        self.call_after_refresh(self._arm_switch_handler)

    def _arm_switch_handler(self) -> None:
        self._suppress_switch = False

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if self._suppress_switch or event.control.id != 'mcp-enable-switch':
            return
        self.post_message(SidebarRow.ToggleRequested(self.item_id))
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

    """A collapsible section with a header and expandable body."""

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
        height: auto;
        min-height: 1;
        width: 100%;
        margin-bottom: 1;
        align: left middle;
        padding-right: 0;
    }
    CollapsibleSection .section-icon {
        width: auto;
        height: 1;
        padding-right: 1;
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
    }
    CollapsibleSection .sidebar-manage-btn {
        dock: right;
        height: 1;
        min-height: 1;
        min-width: 0;
        width: auto;
        padding: 0 1;
        margin: 0 0 0 1;
        border: round #26324f;
        background: #0a1324;
        text-style: none;
        color: #6f83aa;
    }
    CollapsibleSection .sidebar-manage-btn.-mcp {
        border: round #3d3528;
        color: #b89a6a;
        background: #12100c;
    }
    CollapsibleSection .sidebar-manage-btn.-mcp:hover,
    CollapsibleSection .sidebar-manage-btn.-mcp:focus {
        background: #1a1610;
        color: #eacb8a;
        border: round #eacb8a;
    }
    CollapsibleSection .sidebar-manage-btn.-skill {
        border: round #352a45;
        color: #a88fd4;
        background: #100c16;
    }
    CollapsibleSection .sidebar-manage-btn.-skill:hover,
    CollapsibleSection .sidebar-manage-btn.-skill:focus {
        background: #181024;
        color: #c792ea;
        border: round #c792ea;
    }
    CollapsibleSection .collapsible-body {
        width: 100%;
        height: auto;
        margin-left: 0;
    }
    CollapsibleSection .collapsible-body.-hidden {
        display: none;
    }
    CollapsibleSection .thinking-content {
        color: lightgray;
        opacity: 0.7;
    }
    CollapsibleSection .sidebar-footer-hint {
        width: 100%;
        height: 1;
        color: #54597b;
        margin-top: 1;
        padding: 0 1;
    }
    SidebarRow.-view-only:hover {
        background: #0d162a;
    }
    SidebarRow.-disabled:hover {
        background: #0d162a;
    }
    """

    can_focus = True

    BINDINGS = [
        ('enter', 'toggle', 'Toggle Expansion'),
        ('space', 'toggle', 'Toggle Expansion'),
        Binding('a', 'add_item', 'Add', show=False),
        Binding('plus', 'add_item', 'Add', show=False),
    ]

    def __init__(
        self,
        title: str,
        content: str | None = None,
        *,
        collapsed: bool = True,
        accent_color: str = '#91abec',
        section_icon: str = '',
        action_label: str | None = None,
        action_button_class: str = '',
        footer_hint: str | None = None,
        id: str | None = None,
        is_thinking: bool = False,
    ) -> None:
        super().__init__(id=id)
        self._section_title = title
        self._content = content
        self._collapsed = collapsed
        self._accent_color = accent_color
        self._section_icon = section_icon
        self._action_label = action_label
        self._action_button_class = action_button_class
        self._footer_hint = footer_hint
        self._items: list[dict[str, Any]] = []
        self._is_thinking = is_thinking

    def _header_icon_markup(self) -> str:
        if not self._section_icon:
            return ''
        return f'[{self._accent_color}]{self._section_icon}[/]'

    def _header_title_markup(self) -> str:
        caret_icon = '▸' if self._collapsed else '▾'
        caret = f'[#54597b]{caret_icon}[/]'
        title_color = '#6f83aa' if self._collapsed else self._accent_color
        title_part = f'[{title_color}]{self._section_title}[/]'
        return f'{caret} {title_part}'

    @property
    def is_collapsed(self) -> bool:
        return self._collapsed

    def _refresh_header(self) -> None:
        icon = self.query_one('#header-icon', Static)
        header = self.query_one('#header', Static)
        icon.update(self._header_icon_markup())
        header.update(self._header_title_markup())
        header.classes = (
            'collapsible-header collapsed'
            if self._collapsed
            else 'collapsible-header expanded'
        )

    def _empty_markup(self, text: str) -> str:
        return f'[#54597b]{SIDEBAR_BULLET}[/] [#54597b]{text}[/]'

    def _make_row(self, item: dict[str, Any]) -> SidebarRow | McpServerRow:
        if item.get('toggleable'):
            return McpServerRow(
                item['label'],
                item['item_id'],
                enabled=not item.get('disabled', False),
            )
        return SidebarRow(
            item['label'],
            item['item_id'],
            deletable=item['deletable'],
            status=item.get('status'),
            meta=item.get('meta'),
            interactive=item.get('interactive', True),
            toggleable=item.get('toggleable', False),
            disabled=item.get('disabled', False),
            view_only=item.get('view_only', False),
        )

    def compose(self) -> ComposeResult:
        with Horizontal(classes='collapsible-header-row', id='header-row'):
            yield Static(
                self._header_icon_markup(), classes='section-icon', id='header-icon'
            )
            yield Static(
                self._header_title_markup(),
                id='header',
                classes=(
                    'collapsible-header collapsed'
                    if self._collapsed
                    else 'collapsible-header expanded'
                ),
            )
            if self._action_label:
                btn_classes = 'sidebar-manage-btn'
                if self._action_button_class:
                    btn_classes = f'{btn_classes} {self._action_button_class}'
                yield Button(
                    self._action_label,
                    id='action-btn',
                    classes=btn_classes,
                )

        body_classes = (
            'collapsible-body -hidden' if self._collapsed else 'collapsible-body'
        )
        with Vertical(classes=body_classes, id='body'):
            if self._items:
                for item in self._items:
                    yield self._make_row(item)
                if self._footer_hint:
                    yield Static(
                        self._footer_hint,
                        classes='sidebar-footer-hint',
                        id='sidebar-footer-hint',
                    )
            else:
                content_classes = 'empty-text'
                if self._is_thinking:
                    content_classes += ' thinking-content'
                yield Static(
                    self._empty_markup(self._content or ''),
                    id='empty-text',
                    classes=content_classes,
                )

    def toggle(self) -> None:
        """Toggle the collapsed state."""
        self._collapsed = not self._collapsed
        body = self.query_one('#body', Vertical)
        self._refresh_header()

        if self._collapsed:
            body.add_class('-hidden')
        else:
            body.remove_class('-hidden')

    def action_toggle(self) -> None:
        """Action handler for enter/space keypresses."""
        self.toggle()

    def action_add_item(self) -> None:
        """Open the section add flow when an action label is configured."""
        if self._action_label:
            self.post_message(self.ActionClicked(self))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'action-btn':
            self.post_message(self.ActionClicked(self))
            event.stop()

    def on_click(self, event: events.Click) -> None:
        """Handle click events on the header or widget itself."""
        if event.widget and event.widget.id == 'action-btn':
            return

        if event.widget and (
            event.widget.id in ('header', 'header-row', 'header-icon')
            or event.widget == self
        ):
            self.toggle()
            event.prevent_default()
            event.stop()

    def _sync_body_visibility(self) -> None:
        """Keep the body visibility aligned with the collapsed flag."""
        try:
            body = self.query_one('#body', Vertical)
        except Exception:
            return
        if self._collapsed:
            body.add_class('-hidden')
        else:
            body.remove_class('-hidden')

    def _refresh_body_layout(self) -> None:
        """Reflow dynamic sidebar rows after mount/replace."""
        try:
            body = self.query_one('#body', Vertical)
        except Exception:
            return
        self._sync_body_visibility()
        body.refresh(layout=True)
        self.refresh(layout=True)

    def set_content(self, content: str) -> None:
        """Update the body content."""
        self._content = content
        self._items = []
        body = self.query_one('#body', Vertical)
        body.remove_children()
        body.mount(Static(self._empty_markup(content), id='empty-text'))
        self._refresh_body_layout()

    def set_title(self, title: str) -> None:
        """Update the section title."""
        self._section_title = title
        self._refresh_header()

    @staticmethod
    def _normalize_item(
        item: tuple[Any, ...],
    ) -> dict[str, Any]:
        label = str(item[0])
        item_id = str(item[1])
        deletable = bool(item[2]) if len(item) >= 3 else False
        status = item[3] if len(item) >= 4 else None
        meta = item[4] if len(item) >= 5 else None
        interactive = bool(item[5]) if len(item) >= 6 else True
        options = item[6] if len(item) >= 7 and isinstance(item[6], dict) else {}
        return {
            'label': label,
            'item_id': item_id,
            'deletable': deletable,
            'status': status,
            'meta': meta,
            'interactive': interactive,
            'toggleable': bool(options.get('toggleable', False)),
            'disabled': bool(options.get('disabled', False)),
            'view_only': bool(options.get('view_only', False)),
        }

    def set_items(
        self,
        items: list[
            tuple[Any, str]
            | tuple[Any, str, bool]
            | tuple[Any, str, bool, str | None, str | None]
            | tuple[Any, str, bool, str | None, str | None, bool]
            | tuple[Any, str, bool, str | None, str | None, bool, dict[str, Any]]
        ],
    ) -> None:
        """Update the list of interactive items in the body."""
        normalized = [self._normalize_item(item) for item in items]
        self._items = normalized
        body = self.query_one('#body', Vertical)
        body.remove_children()

        if normalized:
            mounts: list[Any] = [self._make_row(item) for item in normalized]
            if self._footer_hint:
                mounts.append(
                    Static(
                        self._footer_hint,
                        classes='sidebar-footer-hint',
                        id='sidebar-footer-hint',
                    )
                )
            body.mount(*mounts)
        else:
            body.mount(
                Static(self._empty_markup(self._content or 'No items'), id='empty-text')
            )
        self._refresh_body_layout()

    def expand(self) -> None:
        """Expand the section."""
        if self._collapsed:
            self.toggle()

    def collapse(self) -> None:
        """Collapse the section."""
        if not self._collapsed:
            self.toggle()
