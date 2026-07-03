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
from textual.widgets import Static, Switch

from backend.cli.theme import (
    NAVY_BRAND,
    NAVY_DOMAIN_SKILLS,
    NAVY_ERROR,
    NAVY_READY,
    NAVY_RUNNING,
    NAVY_TEXT_DIM,
    NAVY_TEXT_MUTED,
    NAVY_WAITING,
)

STATUS_COLORS = {
    'ok': NAVY_READY,
    'err': NAVY_ERROR,
    'warn': NAVY_WAITING,
    'info': NAVY_BRAND,
    'neutral': NAVY_TEXT_MUTED,
    'running': NAVY_RUNNING,
    'skill': NAVY_DOMAIN_SKILLS,
    # Task-tracker statuses (kept distinct from generic "warn" so a
    # blocked task isn't visually identical to a generic warning).
    'todo': NAVY_TEXT_DIM,
    'in_progress': NAVY_RUNNING,
    'done': NAVY_READY,
    'skipped': NAVY_TEXT_MUTED,
    'blocked': NAVY_WAITING,
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
        prefix: str | None = None,
    ) -> None:
        self._label = label
        self._status = status or 'neutral'
        self._meta = meta
        self._prefix = prefix
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
        if self._status == 'skill':
            return STATUS_COLORS['skill']
        if self.view_only:
            return '#8b95a8'
        if not self.interactive:
            return '#8b95a8'
        return STATUS_COLORS.get(self._status, '#969aad')

    def _bullet_glyph(self) -> str:
        if self._disabled or self.view_only:
            return SIDEBAR_BULLET_DIM
        if self._status == 'skill':
            return SIDEBAR_BULLET
        # Task-tracker statuses use the canonical plan-style glyphs
        # so the state is legible from the text, not just from color.
        from backend.core.tasks.task_status import TASK_STATUS_PLAN_ICONS

        task_glyph = TASK_STATUS_PLAN_ICONS.get(self._status)
        if task_glyph is not None:
            return task_glyph
        return SIDEBAR_BULLET

    def _build_markup(self) -> str:
        color = self._bullet_color()
        bullet_part = f'[{color}]{self._bullet_glyph()}[/]'
        prefix_part = f'[{color}]{self._prefix}[/]  ' if self._prefix else ''
        if self._disabled:
            label_part = f'[#54597b][strike]{self._label}[/][/]'
        elif self.view_only:
            label_part = f'[#8b95a8]{self._label}[/]'
        else:
            label_part = f'[#c8d4e8]{self._label}[/]'
        meta_part = f'  [#54597b]{self._meta}[/]' if self._meta else ''
        return f'{bullet_part} {prefix_part}{label_part}{meta_part}'

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
        background: #0f2a22;
        color: #54efae;
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


class SidebarManageButton(Static):
    """Compact header action chip — avoids Textual Button's multi-row tall borders."""

    class Pressed(Message):
        """Posted when the manage chip is activated."""

        def __init__(self, control: 'SidebarManageButton') -> None:
            super().__init__()
            self._control = control

        @property
        def control(self) -> 'SidebarManageButton':
            return self._control

    DEFAULT_CSS = """
    SidebarManageButton {
        dock: right;
        width: auto;
        height: 1;
        min-height: 1;
        min-width: 0;
        padding: 0 1;
        margin: 0 0 0 1;
        content-align: center middle;
        text-style: none;
        color: #6f83aa;
        background: transparent;
        border: none;
    }
    SidebarManageButton:hover {
        color: #91abec;
        background: #101c36;
    }
    SidebarManageButton:focus {
        color: #c8d4e8;
        background: #0e1a30;
    }
    SidebarManageButton.-mcp {
        color: #b89a6a;
        background: #1a1610;
    }
    SidebarManageButton.-mcp:hover,
    SidebarManageButton.-mcp:focus {
        color: #eacb8a;
        background: #252015;
    }
    SidebarManageButton.-skill {
        color: #a88fd4;
        background: #181024;
    }
    SidebarManageButton.-skill:hover,
    SidebarManageButton.-skill:focus {
        color: #c792ea;
        background: #221830;
    }
    """

    def __init__(self, label: str, *, classes: str = '', id: str | None = None) -> None:
        super().__init__(label, classes=classes, id=id)
        self.can_focus = True

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.post_message(self.Pressed(self))

    def on_key(self, event: events.Key) -> None:
        if event.key in ('enter', 'space'):
            event.stop()
            self.post_message(self.Pressed(self))


class CollapsibleSection(Container):
    class ActionClicked(Message):
        """Event fired when the action label is clicked."""

        def __init__(self, control: 'CollapsibleSection') -> None:
            super().__init__()
            self._control = control

        @property
        def control(self) -> 'CollapsibleSection':
            return self._control

    class FeatureToggleChanged(Message):
        """Event fired when the section enable switch is toggled."""

        def __init__(self, control: 'CollapsibleSection', enabled: bool) -> None:
            super().__init__()
            self.control = control
            self.enabled = enabled

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
    CollapsibleSection Switch#feature-switch {
        dock: right;
        width: 4;
        height: 1;
        min-height: 1;
        margin: 0 0 0 1;
        border: none;
        background: transparent;
        padding: 0;
    }
    CollapsibleSection Switch#feature-switch .switch--slider {
        background: #0f1c30;
        color: #54597b;
    }
    CollapsibleSection Switch#feature-switch.-on .switch--slider {
        background: #0f2a22;
        color: #54efae;
    }
    CollapsibleSection Switch#feature-switch:focus {
        border: none;
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
        feature_enabled: bool | None = None,
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
        self._feature_enabled = feature_enabled
        self._suppress_feature_switch = False
        self._items: list[dict[str, Any]] = []
        self._is_thinking = is_thinking

    @property
    def feature_enabled(self) -> bool | None:
        return self._feature_enabled

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
            prefix=item.get('prefix'),
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
                btn_classes = ''
                if self._action_button_class:
                    btn_classes = self._action_button_class
                yield SidebarManageButton(
                    self._action_label,
                    id='action-btn',
                    classes=btn_classes,
                )
            if self._feature_enabled is not None:
                yield Switch(value=self._feature_enabled, id='feature-switch')

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

    def on_sidebar_manage_button_pressed(
        self, event: SidebarManageButton.Pressed
    ) -> None:
        if event.control.id == 'action-btn':
            self.post_message(self.ActionClicked(self))
            event.stop()

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if event.control.id != 'feature-switch':
            return
        if self._suppress_feature_switch:
            self._suppress_feature_switch = False
            return
        enabled = bool(event.value)
        self._feature_enabled = enabled
        self.post_message(self.FeatureToggleChanged(self, enabled))
        event.stop()

    def on_click(self, event: events.Click) -> None:
        """Handle click events on the header or widget itself."""
        if event.widget and getattr(event.widget, 'id', None) == 'action-btn':
            return
        if isinstance(event.widget, Switch):
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

    def set_feature_enabled(self, enabled: bool, *, suppress_event: bool = True) -> None:
        """Sync the header enable switch without posting a toggle event."""
        self._feature_enabled = enabled
        try:
            switch = self.query_one('#feature-switch', Switch)
        except Exception:
            return
        if bool(switch.value) == enabled:
            return
        if suppress_event:
            self._suppress_feature_switch = True
        switch.value = enabled

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
        prefix = options.get('prefix') if options else None
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
            'prefix': prefix,
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
