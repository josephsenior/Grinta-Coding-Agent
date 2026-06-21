"""ScanLineCard — 1-line feed row with state-driven left pipe and ⤢ detail button."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Static

if TYPE_CHECKING:

    from backend.cli.tui.screens.detail.base import DetailScreen


SCAN_LINE_BORDER_COLORS: dict[str, str] = {
    'queued': '#2d4a6a',
    'running': '#EF9F27',
    'done': '#639922',
    'failed': '#E24B4A',
}


class ScanLineCard(Container):
    """1-line transcript card matching OrientLine/ThinkingIndicator chrome.

    State management
    ----------------
    Call :meth:`set_state` to transition through queued / running / done / failed.
    CSS classes (``queued``, ``running``, ``done``, ``failed``) drive the left
    border color.  ``failed`` cards auto-open their detail screen on mount.

    Refresh
    -------
    Subclasses that hold live data should implement :meth:`refresh_summary`
    and write updated text to the ``#scan-summary`` ``Static``.  The 250 ms
    loop calls this method on every mounted card.
    """

    DEFAULT_CSS = """
    ScanLineCard {
        width: 100%;
        height: auto;
        margin: 0;
        border: transparent;
        background: #090d18;
        border-left: solid #2d4a6a;
        padding: 0 1 0 1;
    }
    ScanLineCard.queued {
        border-left: solid #2d4a6a;
        color: $text-muted;
    }
    ScanLineCard.running {
        border-left: solid #EF9F27;
    }
    ScanLineCard.done {
        border-left: solid #639922;
    }
    ScanLineCard.failed {
        border-left: solid #E24B4A;
    }
    ScanLineCard > Horizontal {
        width: 100%;
        height: auto;
    }
    ScanLineCard #scan-summary {
        width: 1fr;
        height: auto;
        content-align: left middle;
        overflow: hidden;
    }
    ScanLineCard #scan-expand {
        width: 3;
        height: auto;
        content-align: right middle;
        color: #54597b;
    }
    ScanLineCard #scan-expand:hover {
        color: #91abec;
    }
    ScanLineCard #scan-delta {
        width: auto;
        min-width: 0;
        height: auto;
        content-align: right middle;
        color: #e2e8f0;
        padding: 0 1 0 0;
    }
    ScanLineCard:focus {
        background: #10192e;
    }
    ScanLineCard:focus #scan-expand {
        color: #91abec;
    }
    """

    BINDINGS = [
        ('enter', 'open_detail', 'Open'),
        ('space', 'open_detail', 'Open'),
    ]

    _state: str = 'queued'

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.can_focus = True
        self.set_state('queued')

    # ── state management ────────────────────────────────────────────

    def set_state(self, state: str) -> None:
        """Transition to *state* and update CSS classes."""
        for cls in ('queued', 'running', 'done', 'failed'):
            self.remove_class(cls)
        self._state = state
        self.add_class(state)
        self._refresh_line()

    @property
    def state_border_color(self) -> str:
        """Left-pipe color for the current card state."""
        return SCAN_LINE_BORDER_COLORS.get(self._state, SCAN_LINE_BORDER_COLORS['queued'])

    def _scan_summary_line(
        self,
        label: str,
        detail: str,
        *,
        detail_max: int = 80,
    ) -> str:
        """Label tinted by state + neutral detail text."""
        text = (detail or '').strip()
        if len(text) > detail_max:
            text = text[: detail_max - 1] + '…'
        from backend.cli.tui.transcript_typography import TX_BODY

        return f'[{self.state_border_color}]{label}[/]  [{TX_BODY}]{text}[/]'

    @property
    def state(self) -> str:
        return self._state

    # ── line text ───────────────────────────────────────────────────

    def _summary_widget(self) -> Static | None:
        try:
            return self.query_one('#scan-summary', Static)
        except Exception:
            return None

    def _delta_widget(self) -> Static | None:
        try:
            return self.query_one('#scan-delta', Static)
        except Exception:
            return None

    def _line_text(self) -> str:
        """Rich markup string for the 1-line summary.  Subclasses MUST override."""
        raise NotImplementedError

    def _delta_text(self) -> str:
        """Rich markup string for the right-aligned delta slot.  Override for +/- stats."""
        return ''

    def _refresh_line(self) -> None:
        sw = self._summary_widget()
        if sw is not None:
            sw.update(self._line_text())
        dw = self._delta_widget()
        if dw is not None:
            dw.update(self._delta_text())

    # ── detail screen factory ───────────────────────────────────────

    def build_detail_screen(self) -> DetailScreen:
        """Return a :class:`DetailScreen` with the full action payload.

        Subclasses MUST override.
        """
        raise NotImplementedError

    def _open_detail(self) -> None:
        if self.app is None:
            return
        self.app.push_screen(self.build_detail_screen())

    def action_open_detail(self) -> None:
        """Keyboard action — open the detail screen for the focused card."""
        self._open_detail()

    # ── compose / mount ─────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static(self._line_text(), id='scan-summary')
            yield Static(self._delta_text(), id='scan-delta')
            yield Static('⤢', id='scan-expand')

    def on_mount(self) -> None:
        if self._state == 'failed':
            self._open_detail()

    # ── click handler ───────────────────────────────────────────────

    def on_click(self, event: events.Click) -> None:
        target = event.widget
        if target is self or (
            hasattr(target, 'id')
            and isinstance(target.id, str)
            and target.id in ('scan-summary', 'scan-expand')
        ):
            self._open_detail()
            event.stop()

    # ── refresh protocol ────────────────────────────────────────────

    def refresh_summary(self) -> None:
        """Update the 1-line summary from live data sources.

        Called every 250 ms by the feed refresh loop.  The default
        implementation is a no-op; subclasses that track live output
        (shell tail, terminal buffer, browser state) override this.
        """
