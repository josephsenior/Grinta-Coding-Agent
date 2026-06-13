"""Unified diff view widget for file-edit previews in the Grinta TUI."""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Literal

from rich.console import Console
from rich.text import Text
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Static

from backend.cli.syntax_theme import get_grinta_rich_syntax_theme
from backend.cli.theme import NAVY_TEXT_MUTED

DIFF_VIEW_PREFIX = '\x1fgrinta-diff-view\x1f'

DiffKind = Literal['ctx', 'add', 'rem', 'hdr']

_HUNK_RE = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')

# Grinta-aligned diff palette (inspired by textual-diff-view unified layout).
_CLR_GUTTER = '#5a6478'
_CLR_GUTTER_ADD = '#6f9f82'
_CLR_GUTTER_REM = '#b87a7a'
_CLR_LINE_CTX = '#c8ceda'
_CLR_LINE_ADD = '#b8f0c8'
_CLR_LINE_REM = '#ffc0c0'
_CLR_BG_CTX = 'transparent'
_CLR_BG_ADD = '#0f2f22'
_CLR_BG_REM = '#351818'
_CLR_INLINE_ADD = '#54efae bold'
_CLR_INLINE_REM = '#fd8383 bold'
_CLR_HDR = '#91abec'


@dataclass(frozen=True)
class DiffViewRow:
    old_no: int | None
    new_no: int | None
    kind: DiffKind
    text: str
    pair_text: str | None = None


def encode_diff_view_payload(
    *,
    path: str = '',
    old_content: str | None = None,
    new_content: str | None = None,
    patch: str | None = None,
    max_lines: int = 200,
) -> str | None:
    """Encode diff preview payload for ActivityCard expansion."""
    if old_content is None and new_content is None and not (patch or '').strip():
        return None
    payload = {
        'path': path or '',
        'old': old_content,
        'new': new_content,
        'patch': patch,
        'max_lines': max_lines,
    }
    return DIFF_VIEW_PREFIX + json.dumps(payload, ensure_ascii=True)


def decode_diff_view_payload(content: str) -> dict[str, Any] | None:
    if not content.startswith(DIFF_VIEW_PREFIX):
        return None
    try:
        payload = json.loads(content[len(DIFF_VIEW_PREFIX) :])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _guess_language(path: str) -> str:
    ext = PurePath(path).suffix.lower()
    mapping = {
        '.py': 'python',
        '.rs': 'rust',
        '.js': 'javascript',
        '.jsx': 'jsx',
        '.ts': 'typescript',
        '.tsx': 'tsx',
        '.json': 'json',
        '.toml': 'toml',
        '.yaml': 'yaml',
        '.yml': 'yaml',
        '.md': 'markdown',
        '.sh': 'bash',
        '.bash': 'bash',
        '.go': 'go',
        '.java': 'java',
        '.rb': 'ruby',
        '.css': 'css',
        '.html': 'html',
        '.sql': 'sql',
        '.diff': 'diff',
    }
    return mapping.get(ext, 'text')


def _syntax_line_text(line: str, language: str) -> Text:
    if not line.strip() or language == 'text':
        return Text(line or ' ', style=_CLR_LINE_CTX)
    try:
        from rich.syntax import Syntax

        console = Console(force_terminal=True, color_system='truecolor', width=4096)
        syntax = Syntax(
            line,
            language,
            theme=get_grinta_rich_syntax_theme(),
            background_color='default',
            word_wrap=False,
            padding=(0, 0),
        )
        rendered = Text()
        for segment, style, _ in console.render(syntax, console.options.update_width(4096)):
            rendered.append(segment, style or _CLR_LINE_CTX)
        return rendered or Text(line or ' ', style=_CLR_LINE_CTX)
    except Exception:
        return Text(line or ' ', style=_CLR_LINE_CTX)


def _word_diff_overlay(base: Text, other: str, *, side: str) -> Text:
    """Apply intra-line highlights for paired add/remove lines."""
    if not other:
        return base
    matcher = difflib.SequenceMatcher(
        lambda ch: ch in {' ', '\t'},
        base.plain,
        other,
    )
    highlight = _CLR_INLINE_REM if side == 'rem' else _CLR_INLINE_ADD
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if side == 'rem' and tag in {'delete', 'replace'}:
            base.stylize(highlight, i1, i2)
        elif side == 'add' and tag in {'insert', 'replace'}:
            base.stylize(highlight, j1, j2)
    return base


def _rows_from_old_new(
    old_content: str,
    new_content: str,
    *,
    max_lines: int = 200,
    n_context: int = 3,
) -> list[DiffViewRow]:
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    rows: list[DiffViewRow] = []

    for group_idx, group in enumerate(matcher.get_grouped_opcodes(n_context)):
        if group_idx > 0:
            if len(rows) >= max_lines:
                break
            rows.append(DiffViewRow(None, None, 'hdr', '…'))
        for tag, i1, i2, j1, j2 in group:
            if tag == 'equal':
                for offset, old_index in enumerate(range(i1, i2)):
                    if len(rows) >= max_lines:
                        return rows
                    new_index = j1 + offset
                    rows.append(
                        DiffViewRow(
                            old_index + 1,
                            new_index + 1,
                            'ctx',
                            old_lines[old_index],
                        )
                    )
            elif tag == 'delete':
                for old_index in range(i1, i2):
                    if len(rows) >= max_lines:
                        return rows
                    rows.append(
                        DiffViewRow(
                            old_index + 1,
                            None,
                            'rem',
                            old_lines[old_index],
                        )
                    )
            elif tag == 'insert':
                for new_index in range(j1, j2):
                    if len(rows) >= max_lines:
                        return rows
                    rows.append(
                        DiffViewRow(
                            None,
                            new_index + 1,
                            'add',
                            new_lines[new_index],
                        )
                    )
            elif tag == 'replace':
                old_slice = old_lines[i1:i2]
                new_slice = new_lines[j1:j2]
                pair_count = max(len(old_slice), len(new_slice))
                for offset in range(pair_count):
                    if len(rows) >= max_lines:
                        return rows
                    old_index = i1 + offset
                    new_index = j1 + offset
                    old_text = old_slice[offset] if offset < len(old_slice) else ''
                    new_text = new_slice[offset] if offset < len(new_slice) else ''
                    if old_text and new_text:
                        rows.append(
                            DiffViewRow(
                                old_index + 1,
                                None,
                                'rem',
                                old_text,
                                pair_text=new_text,
                            )
                        )
                        if len(rows) >= max_lines:
                            return rows
                        rows.append(
                            DiffViewRow(
                                None,
                                new_index + 1,
                                'add',
                                new_text,
                                pair_text=old_text,
                            )
                        )
                    elif old_text:
                        rows.append(
                            DiffViewRow(old_index + 1, None, 'rem', old_text)
                        )
                    elif new_text:
                        rows.append(
                            DiffViewRow(None, new_index + 1, 'add', new_text)
                        )
    return rows


def _rows_from_patch(patch: str, *, max_lines: int = 200) -> list[DiffViewRow]:
    rows: list[DiffViewRow] = []
    old_no = 0
    new_no = 0
    pending_old: list[tuple[int, str]] = []
    pending_new: list[tuple[int, str]] = []

    def flush_pending_pairs() -> None:
        nonlocal pending_old, pending_new
        while pending_old and pending_new:
            old_line_no, old_text = pending_old.pop(0)
            new_line_no, new_text = pending_new.pop(0)
            if len(rows) >= max_lines:
                pending_old = []
                pending_new = []
                return
            rows.append(
                DiffViewRow(old_line_no, None, 'rem', old_text, pair_text=new_text)
            )
            if len(rows) >= max_lines:
                pending_old = []
                pending_new = []
                return
            rows.append(
                DiffViewRow(None, new_line_no, 'add', new_text, pair_text=old_text)
            )
        for old_line_no, old_text in pending_old:
            if len(rows) >= max_lines:
                break
            rows.append(DiffViewRow(old_line_no, None, 'rem', old_text))
        for new_line_no, new_text in pending_new:
            if len(rows) >= max_lines:
                break
            rows.append(DiffViewRow(None, new_line_no, 'add', new_text))
        pending_old = []
        pending_new = []

    for raw_line in patch.splitlines():
        if len(rows) >= max_lines:
            break
        if raw_line.startswith('---') or raw_line.startswith('+++'):
            flush_pending_pairs()
            rows.append(DiffViewRow(None, None, 'hdr', raw_line))
            continue
        if raw_line.startswith('@@'):
            flush_pending_pairs()
            match = _HUNK_RE.match(raw_line)
            if match:
                old_no = int(match.group(1)) - 1
                new_no = int(match.group(3)) - 1
            rows.append(DiffViewRow(None, None, 'hdr', raw_line))
            continue
        if raw_line.startswith('-'):
            old_no += 1
            pending_old.append((old_no, raw_line[1:]))
            continue
        if raw_line.startswith('+'):
            new_no += 1
            pending_new.append((new_no, raw_line[1:]))
            continue
        if raw_line.startswith(' '):
            flush_pending_pairs()
            old_no += 1
            new_no += 1
            rows.append(DiffViewRow(old_no, new_no, 'ctx', raw_line[1:]))
            continue
        flush_pending_pairs()
        rows.append(DiffViewRow(None, None, 'hdr', raw_line))

    flush_pending_pairs()
    return rows


def build_diff_view_rows(
    *,
    path: str = '',
    old_content: str | None = None,
    new_content: str | None = None,
    patch: str | None = None,
    max_lines: int = 200,
) -> list[DiffViewRow]:
    if old_content is not None and new_content is not None:
        return _rows_from_old_new(old_content, new_content, max_lines=max_lines)
    if patch and patch.strip():
        return _rows_from_patch(patch, max_lines=max_lines)
    return []


class UnifiedDiffRow(Horizontal):
    """Single unified diff row with dual gutters and highlighted code."""

    DEFAULT_CSS = """
    UnifiedDiffRow {
        width: 100%;
        height: 1;
    }
    UnifiedDiffRow .diff-gutter {
        width: 5;
        height: 1;
        content-align: right middle;
        padding: 0 1 0 0;
        color: #5a6478;
    }
    UnifiedDiffRow .diff-gutter.add {
        color: #6f9f82;
        background: #0f2f22;
    }
    UnifiedDiffRow .diff-gutter.rem {
        color: #b87a7a;
        background: #351818;
    }
    UnifiedDiffRow .diff-code {
        width: 1fr;
        height: 1;
        padding: 0 1;
    }
    UnifiedDiffRow .diff-code.ctx {
        color: #c8ceda;
    }
    UnifiedDiffRow .diff-code.add {
        background: #0f2f22;
    }
    UnifiedDiffRow .diff-code.rem {
        background: #351818;
    }
    UnifiedDiffRow .diff-code.hdr {
        color: #91abec;
        background: #0a1224;
    }
    UnifiedDiffRow .diff-sign {
        width: 2;
        height: 1;
        content-align: center middle;
        color: #5a6478;
    }
    UnifiedDiffRow .diff-sign.add {
        color: #54efae;
        background: #0f2f22;
    }
    UnifiedDiffRow .diff-sign.rem {
        color: #fd8383;
        background: #351818;
    }
    """

    def __init__(
        self,
        row: DiffViewRow,
        *,
        gutter_width: int,
        language: str,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._row = row
        self._gutter_width = gutter_width
        self._language = language

    def _format_gutter(self, value: int | None) -> str:
        if value is None:
            return ' ' * self._gutter_width
        return f'{value:>{self._gutter_width}}'

    def _render_code(self) -> Text:
        row = self._row
        if row.kind == 'hdr':
            return Text(row.text, style=_CLR_HDR)
        base = _syntax_line_text(row.text, self._language)
        if row.kind == 'rem' and row.pair_text is not None:
            return _word_diff_overlay(base, row.pair_text, side='rem')
        if row.kind == 'add' and row.pair_text is not None:
            return _word_diff_overlay(base, row.pair_text, side='add')
        return base

    def compose(self):
        row = self._row
        sign = {'add': '+', 'rem': '-', 'ctx': ' ', 'hdr': ' '}.get(row.kind, ' ')
        gutter_old = self._format_gutter(row.old_no)
        gutter_new = self._format_gutter(row.new_no)
        yield Static(gutter_old, classes=f'diff-gutter old {row.kind}')
        yield Static(gutter_new, classes=f'diff-gutter new {row.kind}')
        yield Static(sign, classes=f'diff-sign {row.kind}')
        yield Static(self._render_code(), classes=f'diff-code {row.kind}')


class UnifiedDiffView(VerticalScroll):
    """Scrollable unified diff preview with gutters, syntax, and word highlights."""

    DEFAULT_CSS = """
    UnifiedDiffView {
        width: 100%;
        height: auto;
        max-height: 24;
        border: solid #26324f;
        background: #060a14;
        padding: 0;
    }
    UnifiedDiffView .diff-truncated {
        width: 100%;
        height: 1;
        padding: 0 1;
        color: #969aad;
        background: #0a1224;
    }
    """

    def __init__(
        self,
        *,
        path: str = '',
        old_content: str | None = None,
        new_content: str | None = None,
        patch: str | None = None,
        max_lines: int = 200,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._path = path
        self._old_content = old_content
        self._new_content = new_content
        self._patch = patch
        self._max_lines = max_lines

    def compose(self):
        rows = build_diff_view_rows(
            path=self._path,
            old_content=self._old_content,
            new_content=self._new_content,
            patch=self._patch,
            max_lines=self._max_lines,
        )
        if not rows:
            yield Static('No diff available.', classes='diff-truncated')
            return

        gutter_width = 1
        for row in rows:
            for value in (row.old_no, row.new_no):
                if value is not None:
                    gutter_width = max(gutter_width, len(str(value)))

        language = _guess_language(self._path)
        for row in rows:
            yield UnifiedDiffRow(row, gutter_width=gutter_width, language=language)

        total = 0
        if self._patch:
            total = len(self._patch.splitlines())
        elif self._old_content is not None and self._new_content is not None:
            total = max(
                len(self._old_content.splitlines()),
                len(self._new_content.splitlines()),
            )
        if total > len(rows):
            remaining = total - len(rows)
            yield Static(
                f'… {remaining} more lines',
                classes='diff-truncated',
            )


def diff_view_from_encoded(content: str) -> UnifiedDiffView | None:
    payload = decode_diff_view_payload(content)
    if payload is None:
        return None
    return UnifiedDiffView(
        path=str(payload.get('path') or ''),
        old_content=payload.get('old'),
        new_content=payload.get('new'),
        patch=payload.get('patch'),
        max_lines=int(payload.get('max_lines') or 200),
    )
