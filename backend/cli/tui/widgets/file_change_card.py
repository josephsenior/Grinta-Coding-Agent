"""Static scrollable file-change card for create/edit observations."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Static

from backend.cli.theme import NAVY_TEXT_PRIMARY
from backend.cli.tui.widgets.activity_card.diff_lines import _format_file_delta_outcome
from backend.cli.tui.widgets.unified_diff_view import (
    UnifiedDiffView,
    decode_diff_view_payload,
)


class FileChangeCard(Container):
    """Path + delta header with an always-visible scrollable unified diff body."""

    DEFAULT_CSS = """
    FileChangeCard {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
        border: round #1b233a;
        background: #08101d;
        padding: 0 0 1 0;
    }
    FileChangeCard .file-change-header {
        width: 100%;
        height: 1;
        padding: 0 1;
        content-align: left middle;
    }
    FileChangeCard .file-change-body {
        width: 100%;
        height: auto;
        padding: 0 1 0 1;
    }
    """

    def __init__(
        self,
        *,
        display_path: str,
        outcome: str | None = None,
        encoded_diff: str | None = None,
        diff_path: str = '',
        id: str | None = None,
    ) -> None:
        super().__init__(id=id, classes='file-change-card')
        self._display_path = display_path
        self._outcome = outcome
        self._encoded_diff = encoded_diff
        self._diff_path = diff_path or display_path

    @staticmethod
    def _build_header_markup(display_path: str, outcome: str | None) -> str:
        path_part = f'[{NAVY_TEXT_PRIMARY}]{display_path}[/]'
        if not outcome:
            return path_part
        delta = _format_file_delta_outcome(outcome)
        return f'{path_part}  {delta}' if delta else path_part

    def compose(self) -> ComposeResult:
        yield Static(
            self._build_header_markup(self._display_path, self._outcome),
            classes='file-change-header',
            id='file-change-header',
        )
        with Vertical(classes='file-change-body'):
            view = self._build_diff_view()
            if view is not None:
                yield view
            else:
                yield Static('No diff available.', classes='file-change-header')

    def _build_diff_view(self) -> UnifiedDiffView | None:
        encoded = self._encoded_diff
        if not encoded:
            return None
        payload = decode_diff_view_payload(encoded)
        if payload is None:
            return None
        return UnifiedDiffView(
            path=str(payload.get('path') or self._diff_path or ''),
            old_content=payload.get('old'),
            new_content=payload.get('new'),
            patch=payload.get('patch'),
            max_lines=int(payload.get('max_lines') or 200),
        )
