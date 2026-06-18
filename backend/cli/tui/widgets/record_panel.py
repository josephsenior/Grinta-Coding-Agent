"""Record-tier transcript row: scan header + user-expandable body."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Static

from backend.cli.theme import (
    CLR_REASONING_SNAP,
    NAVY_ERROR,
    NAVY_READY,
)

if TYPE_CHECKING:
    from backend.cli.event_rendering.unified_renderer.types import ActivityCard

_RECORD_PIPE: dict[str, str] = {
    'browser': '#3d5a4a',
    'mcp': '#3a3d5a',
    'workers': '#3a4a5a',
    'tool': '#1b233a',
}

_RECORD_PREFIX: dict[str, str] = {
    'browser': '#6a9a7a',
    'mcp': '#7a7a9a',
    'workers': '#7a8a9a',
    'tool': '#91abec',
}

_STATUS_RESULT_COLOR = {
    'ok': NAVY_READY,
    'err': NAVY_ERROR,
    'warn': NAVY_ERROR,
    'running': '#5eead4',
    'neutral': CLR_REASONING_SNAP,
}

_FAMILY_LABEL = {
    'browser': 'Browser',
    'mcp': 'MCP',
    'workers': 'Workers',
    'tool': 'Tool',
}


class RecordPanel(Container):
    """Record-tier tool row — flat header, body collapsed until user expands."""

    DEFAULT_CSS = """
    RecordPanel {
        width: 100%;
        height: auto;
        margin: 0 0 2 0;
        border: none;
        background: #050913;
        padding: 0;
    }
    RecordPanel.-running {
        border-left: heavy #5eead4;
    }
    RecordPanel .record-header-row {
        width: 100%;
        height: 1;
        padding: 0 1 0 2;
    }
    RecordPanel .record-header-text {
        width: 1fr;
        height: 1;
    }
    RecordPanel .record-caret {
        width: 3;
        height: 1;
        content-align: right middle;
        color: #54597b;
    }
    RecordPanel .record-body {
        width: 100%;
        height: auto;
        padding: 0 1 1 2;
    }
    RecordPanel .record-meta {
        width: 100%;
        height: auto;
        color: #54597b;
        padding: 0 0 0 1;
    }
    RecordPanel.-collapsed .record-body-wrap,
    RecordPanel.-collapsed .record-body,
    RecordPanel.-collapsed .record-meta {
        display: none;
    }
    RecordPanel.-collapsed .record-caret {
        color: #54597b;
    }
    RecordPanel.-expanded .record-caret {
        color: #91abec;
    }
    """

    is_pinned = False
    _collapsible = True

    def __init__(
        self,
        *,
        verb: str,
        detail: str,
        badge_category: str = 'tool',
        status: str = 'neutral',
        outcome: str | None = None,
        body: str = '',
        meta_lines: list[str] | None = None,
        processing: bool = False,
        collapsed: bool = True,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.add_class(f'category-{badge_category}')
        pipe = _RECORD_PIPE.get(badge_category, '#1b233a')
        self.styles.border_left = ('solid', pipe)
        self._verb = verb
        self._detail = detail
        self._badge_category = badge_category
        self._status = status
        self._outcome = outcome
        self._body = body or ''
        self._meta_lines = list(meta_lines or [])
        self.processing = processing
        self._collapsed = collapsed
        if collapsed:
            self.add_class('-collapsed')
        else:
            self.add_class('-expanded')

    @classmethod
    def from_activity_card(
        cls,
        card: ActivityCard,
        *,
        processing: bool = False,
        collapsed: bool = True,
    ) -> RecordPanel:
        from backend.cli.event_rendering.unified_renderer import ActivityRenderer

        body = ActivityRenderer.format_extra_lines(card.extra_lines) or ''
        status = {
            'ok': 'ok',
            'err': 'err',
            'warn': 'warn',
            'neutral': 'running' if processing else 'neutral',
        }.get(card.secondary_kind, 'neutral')
        return cls(
            verb=card.verb,
            detail=card.detail,
            badge_category=card.badge_category,
            status=status,
            outcome=card.secondary,
            body=body,
            meta_lines=card.meta_lines,
            processing=processing,
            collapsed=collapsed,
        )

    def should_auto_expand(self) -> bool:
        return False

    def _family_label(self) -> str:
        return _FAMILY_LABEL.get(self._badge_category, 'Tool')

    def _header_text(self) -> Text:
        family = self._family_label()
        prefix_color = _RECORD_PREFIX.get(self._badge_category, '#91abec')
        target = self._detail or '…'
        if self.processing:
            result = self._outcome or '…'
            status_key = 'running'
        else:
            result = self._outcome or ''
            status_key = self._status
        parts: list[tuple[str, str]] = [
            (f'{family}  ', prefix_color),
            (f'{self._verb}  ', prefix_color),
            (target, '#c8d4e8'),
        ]
        if result:
            parts.append((' · ', '#54597b'))
            parts.append(
                (result, _STATUS_RESULT_COLOR.get(status_key, CLR_REASONING_SNAP))
            )
        return Text.assemble(*parts)

    def _caret_char(self) -> str:
        return '▾' if not self._collapsed else '▸'

    def _sync_running_class(self) -> None:
        self.set_class(self.processing, '-running')

    def _refresh_header(self) -> None:
        if not self.is_mounted:
            return
        try:
            self.query_one('.record-header-text', Static).update(self._header_text())
        except Exception:
            pass
        try:
            self.query_one('.record-caret', Static).update(self._caret_char())
        except Exception:
            pass

    def _refresh_body(self) -> None:
        if not self.is_mounted:
            return
        try:
            body = self.query_one('.record-body', Static)
            body.update(self._body or '')
        except Exception:
            pass
        try:
            meta = self.query_one('.record-meta', Static)
            meta_text = '  '.join(self._meta_lines) if self._meta_lines else ''
            meta.update(meta_text)
            meta.display = bool(meta_text) and not self._collapsed
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        with Horizontal(classes='record-header-row'):
            yield Static(
                self._header_text(),
                classes='record-header-text',
            )
            yield Static(self._caret_char(), classes='record-caret')
        with Vertical(classes='record-body-wrap'):
            yield Static(self._body or '', classes='record-body')
            yield Static(
                '  '.join(self._meta_lines) if self._meta_lines else '',
                classes='record-meta',
            )

    def on_mount(self) -> None:
        self._sync_running_class()
        self._refresh_body()

    def collapse(self) -> None:
        if self._collapsed:
            return
        self._collapsed = True
        self.add_class('-collapsed')
        self.remove_class('-expanded')
        self._refresh_header()
        self._refresh_body()

    def expand(self) -> None:
        if not self._collapsed:
            return
        self._collapsed = False
        self.remove_class('-collapsed')
        self.add_class('-expanded')
        self._refresh_header()
        self._refresh_body()

    def toggle_body(self) -> None:
        if self._collapsed:
            self.expand()
        else:
            self.collapse()

    def on_click(self, event: events.Click) -> None:
        target = event.widget
        if target is self or (
            hasattr(target, 'classes')
            and (
                'record-header-text' in target.classes
                or 'record-caret' in target.classes
                or 'record-header-row' in target.classes
            )
        ):
            if self._body or self._meta_lines:
                self.toggle_body()
            event.stop()

    def set_processing(self, processing: bool) -> None:
        self.processing = processing
        if processing:
            self._status = 'running'
        elif self._status == 'running':
            self._status = 'neutral'
        self._sync_running_class()
        self._refresh_header()

    def set_status(self, status: str, outcome: str | None = None) -> None:
        self._status = status
        if outcome is not None:
            self._outcome = outcome
        self._refresh_header()

    def update_content(self, extra_content: str | None) -> None:
        if extra_content is not None:
            self._body = extra_content
        self._refresh_body()

    def set_meta(self, *meta_lines: str) -> None:
        self._meta_lines = [line for line in meta_lines if line]
        self._refresh_body()

    def set_syntax_language(self, _language: str | None) -> None:
        return

    def set_diff_encoded(self, _encoded: bool | None) -> None:
        return
