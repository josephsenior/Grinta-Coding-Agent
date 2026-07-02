"""PayloadDetailScreen — scrollable body for scan-line rows with text payloads."""

from __future__ import annotations

from typing import Any

from textual.widgets import Static

from backend.cli.tui.screens.detail.base import DetailScreen
from backend.cli.tui.screens.detail.helpers import format_meta_chips


class PayloadDetailScreen(DetailScreen):
    """Generic detail view for delegate, MCP, and thinking-artifact rows."""

    def __init__(
        self,
        *,
        kind: str,
        heading: str,
        body: str = '',
        meta_parts: list[str] | None = None,
        accent: str | None = None,
        title: str = '',
    ) -> None:
        super().__init__(
            title=title or f'{kind}  {heading}',
            kind=kind,
            heading=heading,
            accent=accent,
        )
        self._body = body or ''
        self._meta_parts = list(meta_parts or [])

    def build_content(self) -> list:
        widgets: list = []
        if self._meta_parts:
            widgets.append(
                self.meta_row(
                    format_meta_chips(self._meta_parts),
                    widget_id='payload-meta',
                )
            )
        if not self._body.strip():
            widgets.append(self.empty_state('(no output)'))
            return widgets

        from backend.cli.tui.renderer.prep import prep_markdown
        from backend.cli.tui.transcript_typography import TX_BODY

        try:
            renderable = prep_markdown(self._body)
        except Exception:
            renderable = f'[{TX_BODY}]{self._body}[/]'
        widgets.append(
            Static(renderable, classes='detail-prose', id='payload-body'),
        )
        return widgets

    def set_body(self, body: str) -> None:
        """Replace the live body text and re-render the body widget in place.

        Used by streaming-aware cards (e.g. :class:`CompactionCard`) so the
        detail screen can show the summary as it streams in. Safe to call
        repeatedly with the same text; rebuilds the markdown each time.
        """
        self._body = body or ''
        widget: Static | None
        try:
            widget = self.query_one('#payload-body', Static)
        except Exception:
            widget = None
        if widget is None:
            return
        from backend.cli.tui.renderer.prep import prep_markdown
        from backend.cli.tui.transcript_typography import TX_BODY

        if not self._body.strip():
            widget.update('(no output)')
            return
        try:
            renderable = prep_markdown(self._body)
        except Exception:
            renderable = f'[{TX_BODY}]{self._body}[/]'
        widget.update(renderable)

    def on_unmount(self) -> None:
        """Drop the back-pointer from any streaming card that registered us.

        CompactionCard (and any future streaming card) sets itself on the
        screen so it can push updates as text arrives; we clear that link
        when the screen is dismissed so the card no longer references a
        dead widget.
        """
        for attr in ('_live_card', 'streaming_source'):
            src: Any = getattr(self, attr, None)
            if src is not None:
                clear = getattr(src, '_clear_live_detail_screen', None)
                if callable(clear):
                    try:
                        clear(self)
                    except Exception:  # noqa: BLE001
                        pass
                else:
                    if getattr(src, '_live_detail_screen', None) is self:
                        src._live_detail_screen = None
