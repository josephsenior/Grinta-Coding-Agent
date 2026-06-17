"""Static file-change card for create/edit observations."""

from __future__ import annotations

from pathlib import PurePath

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Static

from backend.cli.theme import NAVY_TEXT_MUTED, NAVY_TEXT_PRIMARY, NAVY_TEXT_SECONDARY
from backend.cli.theme.cards import CARD_FILE_DELTA_PILL_BG
from backend.cli.tui.widgets.activity_card.diff_lines import _format_file_delta_outcome
from backend.cli.tui.widgets.unified_diff_view import (
    DIFF_VIEW_CONTEXT_LINES,
    UnifiedDiffView,
    decode_diff_view_payload,
)


class FileChangeCard(Container):
    """Path + delta header with a scroll-aware unified diff body."""

    DEFAULT_CSS = """
    FileChangeCard {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
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
    def _split_path(display_path: str) -> tuple[str, str, str]:
        normalized = display_path.replace('\\', '/')
        if '/' in normalized:
            split_at = normalized.rfind('/')
            dirname = normalized[: split_at + 1]
            filename = normalized[split_at + 1 :]
        else:
            dirname = ''
            filename = normalized
        ext = PurePath(filename).suffix.lstrip('.').lower()
        return dirname, filename, ext

    @staticmethod
    def _build_path_markup(display_path: str) -> str:
        dirname, filename, ext = FileChangeCard._split_path(display_path)
        if not dirname:
            return f'[{NAVY_TEXT_SECONDARY}]{display_path}[/]'
        parts = [
            f'[{NAVY_TEXT_MUTED}]{dirname}[/]',
            f'[{NAVY_TEXT_PRIMARY} bold]{filename}[/]',
        ]
        if ext:
            parts.append(f' [{NAVY_TEXT_MUTED}]{ext}[/]')
        return ''.join(parts)

    @staticmethod
    def _build_header_markup(display_path: str, outcome: str | None) -> str:
        path_part = FileChangeCard._build_path_markup(display_path)
        if not outcome:
            return path_part
        delta = _format_file_delta_outcome(outcome)
        if not delta:
            return path_part
        pill = f'[on {CARD_FILE_DELTA_PILL_BG}] {delta} [/]'
        return f'{path_part}  {pill}'

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
            n_context=int(payload.get('n_context') or DIFF_VIEW_CONTEXT_LINES),
        )
