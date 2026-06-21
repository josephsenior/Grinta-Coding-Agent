"""Base DetailScreen — shared chrome for all scan-line detail views."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Static

from backend.cli.tui.screens.detail.helpers import (
    DETAIL_DEFAULT_ACCENT,
    split_detail_title,
)
from backend.cli.tui.transcript_typography import esc_hint_markup


class DetailScreen(Screen):
    """Reusable detail screen with header and scrollable body.

    Subclasses override :meth:`build_content` to return their widgets.
    Press ``escape`` to return to the feed.
    """

    BINDINGS = [('escape', 'app.pop_screen', 'Back')]

    def __init__(
        self,
        title: str = '',
        *,
        kind: str = '',
        heading: str = '',
        accent: str | None = None,
    ) -> None:
        super().__init__()
        parsed_kind, parsed_heading = split_detail_title(title)
        self._kind = kind or parsed_kind
        self._heading = heading or parsed_heading or title
        self._accent = accent or DETAIL_DEFAULT_ACCENT

    def build_content(self) -> list:
        """Return widgets to place in the scrollable body."""
        raise NotImplementedError

    @property
    def _wrap_content_in_panel(self) -> bool:
        """When True, body widgets sit inside the bordered ``#detail-panel``."""
        return True

    @property
    def _use_scroll_body(self) -> bool:
        """When True, body is a ``VerticalScroll``; otherwise a vertical ``Container``."""
        return True

    def _header_kind_markup(self) -> str:
        label = self._kind or 'Detail'
        return f'[bold {self._accent}]{label}[/]'

    def _header_heading_markup(self) -> str:
        if not self._heading:
            return ''
        return f'[#c8d4e8]{self._heading}[/]'

    def section(self, label: str, *widgets: Static | Container) -> list:
        """Section block with a muted heading and optional body widgets."""
        items: list = [Static(self._section_heading_markup(label), classes='detail-section-hdr')]
        items.extend(widgets)
        return items

    @staticmethod
    def _section_heading_markup(label: str) -> str:
        return f'[bold #8f9fc1]{label}[/]'

    def meta_row(self, markup: str, *, widget_id: str = '') -> Static:
        kwargs: dict = {'classes': 'detail-meta'}
        if widget_id:
            kwargs['id'] = widget_id
        return Static(markup, **kwargs)

    def code_block(self, markup: str, *, widget_id: str = '') -> Static:
        kwargs: dict = {'classes': 'detail-code'}
        if widget_id:
            kwargs['id'] = widget_id
        return Static(markup, **kwargs)

    def syntax_block(self, renderable: Any, *, widget_id: str = '') -> Static:
        kwargs: dict = {'classes': 'detail-syntax'}
        if widget_id:
            kwargs['id'] = widget_id
        return Static(renderable, **kwargs)

    def terminal_frame(self, *widgets: Any, title: str = '') -> Any:
        from backend.cli.tui.widgets.detail_terminal_frame import DetailTerminalFrame

        return DetailTerminalFrame(*widgets, title=title)

    def empty_state(self, message: str, *, widget_id: str = '') -> Static:
        kwargs: dict = {'classes': 'detail-empty'}
        if widget_id:
            kwargs['id'] = widget_id
        return Static(f'[#54597b]{message}[/]', **kwargs)

    def list_row(self, markup: str, *, active: bool = False) -> Static:
        classes = 'detail-list-row detail-list-row-active' if active else 'detail-list-row'
        return Static(markup, classes=classes)

    def compose(self) -> ComposeResult:
        with Container(id='detail-header'):
            with Horizontal(id='detail-header-row'):
                yield Static(self._header_kind_markup(), id='detail-kind')
                yield Static(self._header_heading_markup(), id='detail-heading')
                yield Static(esc_hint_markup('Back'), id='detail-hint')
        body = VerticalScroll if self._use_scroll_body else Container
        with body(id='detail-body'):
            if self._wrap_content_in_panel:
                with Container(id='detail-panel'):
                    for widget in self.build_content():
                        yield widget
            else:
                for widget in self.build_content():
                    yield widget

    def on_mount(self) -> None:
        if not self._wrap_content_in_panel:
            return
        panel = self.query_one('#detail-panel')
        panel.styles.border_left = ('heavy', self._accent)

    DEFAULT_CSS = """
    DetailScreen {
        background: #060a14;
        layout: vertical;
    }
    DetailScreen #detail-header {
        width: 100%;
        height: auto;
        background: #080c18;
        border-bottom: solid #1e293b;
        padding: 0 2;
    }
    DetailScreen #detail-header-row {
        width: 100%;
        height: 2;
        align: left middle;
    }
    DetailScreen #detail-kind {
        width: auto;
        min-width: 8;
        height: 1;
        content-align: left middle;
        padding-right: 1;
    }
    DetailScreen #detail-heading {
        width: 1fr;
        height: 1;
        content-align: left middle;
        text-style: bold;
        color: #e9e9e9;
        overflow: hidden;
    }
    DetailScreen #detail-hint {
        width: auto;
        height: 1;
        content-align: right middle;
        color: #c8d4e8;
    }
    DetailScreen #detail-body {
        width: 100%;
        height: 1fr;
        padding: 1 2 2 2;
        scrollbar-size-vertical: 1;
        scrollbar-color: #334155 #060a14;
        scrollbar-color-hover: #475569 #060a14;
        scrollbar-color-active: #64748b #060a14;
    }
    DetailScreen #detail-panel {
        width: 100%;
        height: auto;
        background: #090d18;
        border: solid #1b233a;
        padding: 1 2;
    }
    DetailScreen .detail-section-hdr {
        width: 100%;
        height: auto;
        margin: 0;
        padding: 0 0 0 0;
        color: #8f9fc1;
        border-bottom: solid #1b233a;
    }
    DetailScreen .detail-meta {
        width: 100%;
        height: auto;
        padding: 0 0 1 0;
        color: #969aad;
    }
    DetailScreen .detail-code {
        width: 100%;
        height: auto;
        padding: 0;
        background: #060a14;
        border: solid #1b233a;
        color: #c8d4e8;
    }
    DetailScreen .detail-syntax {
        width: 100%;
        height: auto;
        padding: 0;
        background: #060a14;
        border: none;
        color: #c8d4e8;
    }
    DetailScreen .detail-empty {
        width: 100%;
        height: auto;
        padding: 2 0;
        color: #54597b;
        text-align: center;
    }
    DetailScreen .detail-list-row {
        width: 100%;
        height: auto;
        padding: 0 0 0 1;
        color: #c8d4e8;
    }
    DetailScreen .detail-list-row-active {
        border-left: solid #5eead4;
        padding-left: 1;
        color: #e9e9e9;
    }
    DetailScreen .detail-kv-name {
        color: #c8d4e8;
    }
    DetailScreen .detail-kv-value {
        color: #91abec;
    }
    DetailScreen .detail-url {
        color: #91abec;
        text-style: bold;
    }
    DetailScreen .detail-prose {
        width: 100%;
        height: auto;
        padding: 0;
        color: #c8d4e8;
    }
    DetailScreen .detail-syntax-error {
        width: 100%;
        height: auto;
        margin-top: 1;
        padding: 1;
        background: #1a1218;
        border: solid #E24B4A;
        border-left: heavy #E24B4A;
        color: #E24B4A;
    }
    """
