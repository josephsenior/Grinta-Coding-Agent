"""EditDetailScreen — full unified diff with optional syntax error banner."""

from __future__ import annotations

from textual.widgets import Static

from backend.cli.tui.screens.detail.base import DetailScreen


class EditDetailScreen(DetailScreen):
    """Full file-edit diff or new-file content with syntax error display."""

    DEFAULT_CSS = """
    EditDetailScreen UnifiedDiffView {
        width: 100%;
        height: auto;
        border: none;
        background: transparent;
    }
    """

    def __init__(
        self,
        title: str = 'Edit',
        encoded_diff: str | None = None,
        syntax_error: str | None = None,
        *,
        kind: str = '',
        heading: str = '',
        accent: str | None = None,
    ) -> None:
        super().__init__(
            title=title,
            kind=kind or ('Created' if title.startswith('Created') else 'Edited'),
            heading=heading,
            accent=accent,
        )
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
                path = str(payload.get('path') or '')
                view = UnifiedDiffView(
                    path=path,
                    old_content=payload.get('old'),
                    new_content=payload.get('new'),
                    patch=payload.get('patch'),
                    max_lines=1_000_000,
                )
                frame_title = path.rsplit('/', 1)[-1] if path else 'diff'
                widgets.append(self.terminal_frame(view, title=frame_title))
            else:
                widgets.extend(
                    self.section(
                        'Diff',
                        self.code_block(self._encoded_diff, widget_id='edit-raw-diff'),
                    )
                )
        else:
            widgets.append(self.empty_state('No diff available.', widget_id='edit-no-diff'))

        if self._syntax_error:
            error_text = (
                f'[bold #E24B4A]Syntax Error[/]\n[#E24B4A]{self._syntax_error}[/]'
            )
            widgets.append(Static(error_text, classes='detail-syntax-error', id='edit-syntax-error'))

        return widgets
