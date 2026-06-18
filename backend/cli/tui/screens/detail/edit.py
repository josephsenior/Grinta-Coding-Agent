"""EditDetailScreen — full unified diff with optional syntax error banner."""

from __future__ import annotations

from textual.containers import Vertical
from textual.widgets import Static

from backend.cli.tui.screens.detail.base import DetailScreen


class EditDetailScreen(DetailScreen):
    """Full file-edit diff or new-file content with syntax error display."""

    DEFAULT_CSS = """
    EditDetailScreen #detail-body > UnifiedDiffView {
        height: 1fr;
        min-height: 0;
    }
    EditDetailScreen #detail-body > UnifiedDiffView.-scrollable {
        height: 1fr;
        overflow-y: auto;
    }
    EditDetailScreen #detail-body > UnifiedDiffView.-compact {
        height: auto;
    }
    """

    def __init__(
        self,
        title: str = 'Edit',
        encoded_diff: str | None = None,
        syntax_error: str | None = None,
    ) -> None:
        super().__init__(title=title)
        self._encoded_diff = encoded_diff
        self._syntax_error = syntax_error

    def build_content(self) -> list:
        widgets: list = []

        if self._encoded_diff:
            from backend.cli.tui.widgets.unified_diff_view import (
                UnifiedDiffView,
                decode_diff_view_payload,
            )

            payload = decode_diff_view_payload(self._encoded_diff)
            if payload is not None:
                view = UnifiedDiffView(
                    path=str(payload.get('path') or ''),
                    old_content=payload.get('old'),
                    new_content=payload.get('new'),
                    patch=payload.get('patch'),
                )
                widgets.append(view)
            else:
                widgets.append(Static(self._encoded_diff, id='edit-raw-diff'))
        else:
            widgets.append(Static('No diff available.', id='edit-no-diff'))

        if self._syntax_error:
            error_text = (
                f'[bold #E24B4A]Syntax Error:[/] [#E24B4A]{self._syntax_error}[/]'
            )
            widgets.append(Static(error_text, id='edit-syntax-error'))

        return widgets
