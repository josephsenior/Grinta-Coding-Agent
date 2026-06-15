"""Diff line widgets and encode/decode helpers for ActivityCard bodies."""

from __future__ import annotations

import json

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static

from backend.cli.theme import NAVY_ERROR, NAVY_READY, NAVY_TEXT_DIM, NAVY_TEXT_MUTED
from backend.cli.tui.widgets.activity_card.constants import (
    DIFF_ADD_PREFIX,
    DIFF_CTX_PREFIX,
    DIFF_REM_PREFIX,
    DIFF_SPLIT_PREFIX,
)


class DiffLine(Static):
    """Full-width row for file preview and edit diff lines."""

    DEFAULT_CSS = """
    DiffLine {
        width: 100%;
        height: 1;
        padding: 0 1;
    }
    DiffLine.add {
        background: #0f2f22;
        color: #7de6a1;
    }
    DiffLine.rem {
        background: #351818;
        color: #ff9a9a;
    }
    DiffLine.ctx {
        background: transparent;
        color: #969aad;
    }
    """

    _STYLE_BY_KIND = {
        'add': '#7de6a1',
        'rem': '#ff9a9a',
        'ctx': NAVY_TEXT_MUTED,
    }

    def __init__(self, text: str, kind: str, *, id: str | None = None) -> None:
        super().__init__(
            Text(text, style=self._STYLE_BY_KIND.get(kind, NAVY_TEXT_MUTED)),
            id=id,
        )
        self.add_class(kind)


class SplitDiffLine(Container):
    """Two-pane row for before/after file edit hunks."""

    DEFAULT_CSS = """
    SplitDiffLine {
        width: 100%;
        height: 1;
        layout: horizontal;
    }
    SplitDiffLine .split-pane {
        width: 1fr;
        height: 1;
        padding: 0 1;
    }
    SplitDiffLine .split-pane.left {
        border-right: solid #26324f;
    }
    SplitDiffLine .split-pane.add {
        background: #0f2f22;
        color: #7de6a1;
    }
    SplitDiffLine .split-pane.rem {
        background: #351818;
        color: #ff9a9a;
    }
    SplitDiffLine .split-pane.ctx {
        background: transparent;
        color: #969aad;
    }
    """

    _STYLE_BY_KIND = DiffLine._STYLE_BY_KIND

    def __init__(
        self,
        left: str,
        right: str,
        left_kind: str,
        right_kind: str,
        *,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.left_text = left
        self.right_text = right
        self.left_kind = left_kind
        self.right_kind = right_kind

    def compose(self) -> ComposeResult:
        left_style = self._STYLE_BY_KIND.get(self.left_kind, NAVY_TEXT_MUTED)
        right_style = self._STYLE_BY_KIND.get(self.right_kind, NAVY_TEXT_MUTED)
        yield Static(
            Text(self.left_text or ' ', style=left_style),
            classes=f'split-pane left {self.left_kind}',
        )
        yield Static(
            Text(self.right_text or ' ', style=right_style),
            classes=f'split-pane right {self.right_kind}',
        )


def encode_diff_line(text: str, kind: str) -> str:
    prefix = {
        'add': DIFF_ADD_PREFIX,
        'rem': DIFF_REM_PREFIX,
        'ctx': DIFF_CTX_PREFIX,
    }.get(kind, DIFF_CTX_PREFIX)
    return f'{prefix}{text}'


def encode_split_diff_line(
    left: str,
    right: str,
    left_kind: str,
    right_kind: str,
) -> str:
    payload = {
        'left': left,
        'right': right,
        'left_kind': left_kind,
        'right_kind': right_kind,
    }
    return DIFF_SPLIT_PREFIX + json.dumps(payload, ensure_ascii=True)


def _decode_diff_line(line: str) -> tuple[str, str] | None:
    for prefix, kind in (
        (DIFF_ADD_PREFIX, 'add'),
        (DIFF_REM_PREFIX, 'rem'),
        (DIFF_CTX_PREFIX, 'ctx'),
    ):
        if line.startswith(prefix):
            return kind, line[len(prefix) :]
    return None


def _decode_split_diff_line(line: str) -> tuple[str, str, str, str] | None:
    if not line.startswith(DIFF_SPLIT_PREFIX):
        return None
    try:
        payload = json.loads(line[len(DIFF_SPLIT_PREFIX) :])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    left = str(payload.get('left') or '')
    right = str(payload.get('right') or '')
    left_kind = str(payload.get('left_kind') or 'ctx')
    right_kind = str(payload.get('right_kind') or 'ctx')
    return left, right, left_kind, right_kind


def _format_file_delta_outcome(outcome: str) -> str | None:
    """Return independently colored +N/-N file delta tokens."""
    tokens = outcome.replace(',', ' ').replace('·', ' ').split()
    if not tokens:
        return None

    parts: list[str] = []
    has_delta = False
    for token in tokens:
        if token.startswith('+') and token[1:].isdigit():
            parts.append(f'[{NAVY_READY}]{token}[/]')
            has_delta = True
        elif token.startswith('-') and token[1:].isdigit():
            parts.append(f'[{NAVY_ERROR}]{token}[/]')
            has_delta = True
        else:
            parts.append(f'[{NAVY_TEXT_DIM}]{token}[/]')

    return '  '.join(parts) if has_delta else None
