"""PayloadDetailScreen — scrollable body for scan-line rows with text payloads."""

from __future__ import annotations

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
