"""Concrete transcript action cards — one per agent action type."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from rich.console import Group
from rich.text import Text
from textual.widgets import Static

from backend.cli.theme import NAVY_RUNNING
from backend.cli.tui.widgets.glyphs import glyph as _glyph
from backend.cli.tui.widgets.scan_line.card import ScanLineCard

if TYPE_CHECKING:
    from backend.cli.tui.screens.detail.base import DetailScreen


# ── helpers ────────────────────────────────────────────────────────────


def _truncate(text: str, max_len: int = 80) -> str:
    t = text.strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + '…'


def _compact_path(display_path: str, max_len: int = 40) -> str:
    if len(display_path) <= max_len:
        return display_path
    parts = display_path.replace('\\', '/').split('/')
    if len(parts) <= 2:
        return _truncate(display_path, max_len)
    return f'…/{"/".join(parts[-2:])}'


def _parse_syntax_badge(content: str) -> str | None:
    """Return ``'pass'``, ``'fail'``, or ``None`` from an observation content string."""
    if not content:
        return None
    if '<SYNTAX_CHECK_PASSED' in content:
        return 'pass'
    if '<SYNTAX_CHECK_FAILED>' in content:
        return 'fail'
    return None


def _extract_syntax_error(content: str) -> str | None:
    """Extract the error detail from a ``<SYNTAX_CHECK_FAILED>…</SYNTAX_CHECK_FAILED>`` block."""
    if '<SYNTAX_CHECK_FAILED>' not in content:
        return None
    start = content.index('<SYNTAX_CHECK_FAILED>') + len('<SYNTAX_CHECK_FAILED>')
    end = (
        content.index('</SYNTAX_CHECK_FAILED>', start)
        if '</SYNTAX_CHECK_FAILED>' in content[start:]
        else len(content)
    )
    return content[start:end].strip() or None


def _format_diff_delta(added: int, removed: int) -> str:
    parts: list[str] = []
    if added:
        parts.append(f'+{added}')
    if removed:
        parts.append(f'-{removed}')
    return ' '.join(parts) if parts else '0'


def _task_description(task: dict[str, Any]) -> str:
    return str(
        task.get('description')
        or task.get('title')
        or task.get('task')
        or task.get('id')
        or 'Untitled task'
    ).strip()


def _task_blocked_reason(task: dict[str, Any]) -> str:
    return str(task.get('blocked_reason') or task.get('reason') or '').strip()


def _criterion_assertion(item: dict[str, Any]) -> str:
    return str(
        item.get('assertion') or item.get('description') or item.get('criterion') or ''
    ).strip()


_INLINE_PAYLOAD_LINES = 8


def _bounded_text(
    text: str,
    *,
    max_lines: int,
    tail: bool = False,
) -> tuple[str, int]:
    """Return a bounded transcript preview and the number of hidden lines."""
    lines = (text or '').strip().splitlines()
    if not lines:
        return '', 0
    hidden = max(0, len(lines) - max_lines)
    kept = lines[-max_lines:] if tail and hidden else lines[:max_lines]
    return '\n'.join(kept), hidden


def _section_label(label: str) -> Text:
    from backend.cli.tui.transcript_typography import TX_META

    return Text(label.upper(), style=TX_META)


def _hidden_lines_text(hidden: int, *, earlier: bool = False) -> Text | None:
    if hidden <= 0:
        return None
    from backend.cli.tui.transcript_typography import TX_MUTED

    position = ' earlier' if earlier else ''
    label = 'line' if hidden == 1 else 'lines'
    return Text(f'… {hidden}{position} {label} hidden', style=TX_MUTED)


def _command_text(command: str) -> Text:
    """Render a command exactly as submitted, including multiline commands."""
    from backend.cli.tui.transcript_typography import TX_BODY, TX_KEY_HINT

    lines = (command or '').splitlines() or ['']
    rendered = Text()
    for index, line in enumerate(lines):
        if index:
            rendered.append('\n')
        rendered.append('$ ' if index == 0 else '  ', style=TX_KEY_HINT)
        rendered.append(line, style=TX_BODY)
    return rendered


def _command_output_preview(command: str, output: str) -> Group:
    """Render the complete command and output for inline shell/terminal cards."""
    renderables: list[Any] = [_section_label('Command'), _command_text(command)]
    rendered_output = (output or '').rstrip('\n')
    if rendered_output:
        from backend.cli.tui.transcript_typography import TX_BODY_DIM

        renderables.extend(
            (_section_label('Output'), Text(rendered_output, style=TX_BODY_DIM))
        )
    return Group(*renderables)


def _terminal_inline_widgets(
    command: str,
    output: str,
    *,
    title: str,
    state: str,
    exit_code: int | None = None,
) -> list[Static]:
    """Build a full-height terminal surface with no nested scrolling."""
    chrome = _terminal_chrome(title, state=state, exit_code=exit_code)
    widgets = [
        Static(chrome, classes='terminal-chrome'),
        Static(_command_text(command), classes='terminal-command'),
        Static('', classes='terminal-output scan-inline-content'),
    ]
    rendered_output = (output or '').rstrip('\n')
    if rendered_output:
        from backend.cli.tui.transcript_typography import TX_BODY_DIM

        widgets[-1].update(Text(rendered_output, style=TX_BODY_DIM))
    return widgets


def _terminal_chrome(
    title: str,
    *,
    state: str,
    exit_code: int | None = None,
) -> Text:
    """Render terminal window chrome with a compact, non-border state signal."""
    chrome = Text()
    chrome.append('●', style='#E24B4A')
    chrome.append(' ●', style='#D9A441')
    chrome.append(' ●', style='#639922')
    chrome.append(f'  {_truncate(title.upper(), 28)}', style='#70839c')

    if state == 'running':
        frame = _RUNNING_ELLIPSIS_FRAMES[_running_ellipsis_frame]
        chrome.append(f'  ● RUNNING {frame}', style=NAVY_RUNNING)
    elif state == 'done':
        chrome.append('  ✓ SUCCESS · EXIT 0', style='#639922')
    elif state == 'failed':
        code = exit_code if exit_code is not None else '?'
        chrome.append(f'  ✕ FAILED · EXIT {code}', style='#E24B4A')
    elif state == 'background':
        chrome.append('  ↗ DETACHED', style='#6B9FD4')
    else:
        chrome.append(f'  ○ {state.upper()}', style='#70839c')
    return chrome


def _payload_preview(
    body: str,
    *,
    label: str = 'Result',
    max_lines: int = _INLINE_PAYLOAD_LINES,
) -> Group | None:
    preview, hidden = _bounded_text(body, max_lines=max_lines)
    if not preview:
        return None
    from backend.cli.tui.renderer.prep import prep_markdown

    renderables: list[Any] = [_section_label(label), prep_markdown(preview)]
    omitted = _hidden_lines_text(hidden)
    if omitted is not None:
        renderables.append(omitted)
    return Group(*renderables)


_RUNNING_ELLIPSIS_FRAMES = ('…', '..', '.')
_running_ellipsis_frame = 0


def advance_running_ellipsis_frame() -> None:
    """Advance the running-state ellipsis animation (called every 250 ms)."""
    global _running_ellipsis_frame
    _running_ellipsis_frame = (_running_ellipsis_frame + 1) % len(
        _RUNNING_ELLIPSIS_FRAMES
    )


def _running_ellipsis_markup() -> str:
    glyph = _RUNNING_ELLIPSIS_FRAMES[_running_ellipsis_frame]
    return f'[{NAVY_RUNNING}]{glyph}[/]'


def _status_indicator_markup(
    state: str,
    *,
    exit_code: int | None = None,
    running_tail: str = '',
) -> str:
    """Right-slot status glyph for shell/terminal scan rows."""
    if state == 'running':
        tail = (running_tail or '').strip()
        if tail and tail not in _RUNNING_ELLIPSIS_FRAMES:
            return f'[{NAVY_RUNNING}]{_truncate(tail, 40)}[/]'
        return _running_ellipsis_markup()
    if state == 'background':
        return '[#6B9FD4]detached[/]'
    if state == 'done':
        return f'[scan-line-state-done]{_glyph("✓")}[/]'
    if state == 'failed':
        if exit_code is not None:
            return f'[scan-line-state-failed]{_glyph("✗")} {exit_code}[/]'
        return f'[scan-line-state-failed]{_glyph("✗")}[/]'
    return ''


# One unique icon per scan-line verb — no sharing between card kinds.
# When accessible mode is active, _glyph() substitutes ASCII equivalents.
_SCAN_LINE_ICONS: dict[str, str] = {
    'Agent': '◎',
    'Created': '+',
    'Edited': '↲',
    'Undo': '↶',
    'Shell': '$',
    'Terminal': '▸',
    'Browser': '⌁',
    'Debug': '⎇',
    'Delegated': '⇢',
    'Called': '⊛',
    'Found': 'ƒ',
    'Read': '↳',
    'Verified': '⊢',
    'Analyzed': '≡',
    'Shared Board': '⊞',
    'Compacting': '◈',
    'Compacted': '◇',
    'Defined': '⊡',
    'Updated': '⊜',
    'Viewed': '⊙',
    'Audited': '⊠',
    'Tasks': '▣',
}


def _scan_label_with_icon(label: str) -> str:
    """Prefix a scan-line verb with its icon when one is defined."""
    icon = _SCAN_LINE_ICONS.get(label, '')
    if not icon:
        return label
    return f'{_glyph(icon)} {label}'


def _file_change_chrome(
    path: str,
) -> Text:
    """Render a quiet file header; the diff itself explains the operation."""
    chrome = Text()
    chrome.append(_glyph('▰'), style='#91abec')
    chrome.append(f'  {_compact_path(path, 72)}', style='#c8d4e8 bold')
    return chrome


# ── AgentMessageCard ───────────────────────────────────────────────────


class AgentMessageCard(ScanLineCard):
    """1-line agent message summary — full markdown in detail screen."""

    DEFAULT_CSS = """
    AgentMessageCard {
        border-left: none;
    }
    """

    def __init__(self, text: str, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._text = text

    def _line_text(self) -> str:
        from backend.cli.tui.transcript_typography import TX_BODY, TX_LABEL

        return f'[{TX_LABEL}]{_scan_label_with_icon("Agent")}[/]  [{TX_BODY}]{_truncate(self._text, 80)}[/]'

    def build_detail_screen(self) -> DetailScreen:
        from backend.cli.tui.screens.detail import MessageDetailScreen

        return MessageDetailScreen(
            message_text=self._text,
            accent=self.state_border_color,
        )


# ── EditCard ───────────────────────────────────────────────────────────


class EditCard(ScanLineCard):
    """File edit summary with its syntax-aware diff visible in the transcript.

    Shared across ``create_file``, ``insert_text``, ``replace_string``,
    ``multiedit``, and ``undo_last_edit``.
    """

    DEFAULT_CSS = """
    EditCard,
    EditCard.queued,
    EditCard.running,
    EditCard.background,
    EditCard.done,
    EditCard.failed {
        border: none;
        background: transparent;
        padding: 0;
    }
    EditCard > Horizontal {
        display: none;
    }
    EditCard > .scan-inline {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
        padding: 0;
        border: none;
        background: #070b14;
    }
    EditCard > .scan-inline > .file-chrome {
        width: 100%;
        height: 1;
        padding: 0 1;
        background: #111827;
        color: #70839c;
    }
    EditCard > .scan-inline > UnifiedDiffView,
    EditCard.queued > .scan-inline > UnifiedDiffView,
    EditCard.running > .scan-inline > UnifiedDiffView,
    EditCard.background > .scan-inline > UnifiedDiffView,
    EditCard.done > .scan-inline > UnifiedDiffView,
    EditCard.failed > .scan-inline > UnifiedDiffView {
        border: none;
    }
    EditCard > .scan-inline > .scan-inline-content,
    EditCard > .scan-inline > .scan-inline-error {
        width: 100%;
        height: auto;
        margin: 0;
        padding: 1;
    }
    """

    def __init__(
        self,
        display_path: str,
        *,
        added: int = 0,
        removed: int = 0,
        is_create: bool = False,
        is_undo: bool = False,
        encoded_diff: str | None = None,
        syntax_pass: bool | None = None,
        syntax_error: str | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._display_path = display_path
        self._added = added
        self._removed = removed
        self._is_create = is_create
        self._is_undo = is_undo
        self._encoded_diff = encoded_diff
        self._syntax_pass = syntax_pass
        self._syntax_error = syntax_error
        if is_undo:
            self.add_class('-undone')
        else:
            self.add_class('-created' if is_create else '-edited')
        self._finalize_state()

    @property
    def has_detail(self) -> bool:
        """Edits are complete inline, so they do not need an expand action."""
        return False

    @property
    def state_border_color(self) -> str:
        if self._is_undo and self._state != 'failed':
            from backend.cli.tui.transcript_typography import EDIT_CARD_ACCENT

            return EDIT_CARD_ACCENT
        if not self._is_create and self._state != 'failed':
            from backend.cli.tui.transcript_typography import EDIT_CARD_ACCENT

            return EDIT_CARD_ACCENT
        from backend.cli.tui.widgets.scan_line.card import SCAN_LINE_BORDER_COLORS

        return SCAN_LINE_BORDER_COLORS.get(
            self._state, SCAN_LINE_BORDER_COLORS['queued']
        )

    def _edit_verb(self) -> str:
        if self._is_undo:
            return 'Undo'
        if self._is_create:
            return 'Created'
        return 'Edited'

    def _finalize_state(self) -> None:
        if self._syntax_pass is False:
            self.set_state('failed')
        elif self._added or self._removed or self._is_create:
            self.set_state('done')
        else:
            self.set_state('done')

    def _line_text(self) -> str:
        path = _compact_path(self._display_path)
        return self._scan_summary_line(_glyph('▰'), path, detail_max=72)

    def _delta_text(self) -> str:
        return ''

    def _inline_widgets(self) -> list:
        widgets: list = [
            Static(
                _file_change_chrome(
                    self._display_path,
                ),
                classes='file-chrome',
            )
        ]
        if self._encoded_diff:
            from backend.cli.tui.widgets.unified_diff_view import (
                UnifiedDiffView,
                decode_diff_view_payload,
            )

            payload = decode_diff_view_payload(self._encoded_diff)
            if payload is not None:
                patch = payload.get('patch')
                old_content = payload.get('old')
                new_content = payload.get('new')
                if patch:
                    full_row_budget = len(str(patch).splitlines()) + 1
                else:
                    full_row_budget = (
                        len((old_content or '').splitlines())
                        + len((new_content or '').splitlines())
                        + 1
                    )
                diff_view = UnifiedDiffView(
                    path=str(payload.get('path') or self._display_path),
                    old_content=old_content,
                    new_content=new_content,
                    patch=patch,
                    max_lines=max(full_row_budget, 1),
                    n_context=int(payload.get('n_context') or 2),
                    inline_expanded=True,
                )
                diff_view.styles.border = ('none', 'transparent')
                widgets.append(diff_view)
            else:
                from backend.cli.tui.transcript_typography import TX_BODY_DIM

                widgets.append(
                    Static(
                        Text(self._encoded_diff, style=TX_BODY_DIM),
                        classes='scan-inline-content',
                    )
                )
        if self._syntax_error:
            widgets.append(
                Static(
                    Text(f'Syntax error: {self._syntax_error}', style='#E24B4A'),
                    classes='scan-inline-error',
                )
            )
        return widgets

    def build_detail_screen(self) -> DetailScreen:
        from backend.cli.tui.screens.detail import EditDetailScreen

        verb = self._edit_verb()
        return EditDetailScreen(
            title=f'{verb}  {self._display_path}',
            kind=verb,
            heading=_compact_path(self._display_path),
            accent=self.state_border_color,
            encoded_diff=self._encoded_diff,
            syntax_error=self._syntax_error,
        )


# ── ShellCard ──────────────────────────────────────────────────────────


class ShellCard(ScanLineCard):
    """Shell command rendered as a complete inline terminal surface."""

    DEFAULT_CSS = """
    ShellCard,
    ShellCard.queued,
    ShellCard.running,
    ShellCard.background,
    ShellCard.done,
    ShellCard.failed,
    TerminalCard,
    TerminalCard.queued,
    TerminalCard.running,
    TerminalCard.background,
    TerminalCard.done,
    TerminalCard.failed {
        border: none;
        background: transparent;
        padding: 0;
    }
    ShellCard > Horizontal, TerminalCard > Horizontal {
        display: none;
    }
    ShellCard > .scan-inline, TerminalCard > .scan-inline {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
        padding: 0;
        border: none;
        background: #05080d;
        color: #a9b7c9;
    }
    ShellCard > .scan-inline > .terminal-chrome,
    TerminalCard > .scan-inline > .terminal-chrome {
        width: 100%;
        height: 1;
        padding: 0 1;
        background: #111827;
        color: #70839c;
    }
    ShellCard > .scan-inline > .terminal-command,
    TerminalCard > .scan-inline > .terminal-command {
        width: 100%;
        height: auto;
        padding: 1 1 0 1;
        background: #05080d;
        color: #d7e0ec;
    }
    ShellCard > .scan-inline > .terminal-output,
    TerminalCard > .scan-inline > .terminal-output {
        width: 100%;
        height: auto;
        padding: 0 1 1 1;
        background: #05080d;
        color: #9aa8b8;
    }
    """

    def __init__(
        self,
        command: str,
        *,
        output: str = '',
        exit_code: int | None = None,
        cwd: str = '',
        is_background: bool = False,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.command = command
        self.output = output
        self.exit_code = exit_code
        self.cwd = cwd
        self.is_background = is_background
        self._apply_initial_state()

    @property
    def has_detail(self) -> bool:
        """The complete command and output already live in the transcript."""
        return False

    def _apply_initial_state(self) -> None:
        if self.is_background:
            self.set_state('background')
        elif self.exit_code == 0:
            self.set_state('done')
        elif self.exit_code is not None:
            self.set_state('failed')
        else:
            self.set_state('running')

    def _latest_line(self) -> str:
        if not self.output:
            return '…'
        lines = self.output.strip().split('\n')
        return _truncate(lines[-1].strip(), 60)

    def _result_text(self) -> str:
        if self.is_background:
            return 'detached'
        if self.exit_code == 0:
            return '✓'
        if self.exit_code is not None:
            return f'exit {self.exit_code}'
        return self._latest_line()

    def _line_text(self) -> str:
        label = _scan_label_with_icon('Shell')
        if self.cwd:
            return self._scan_summary_line(label, self.cwd, detail_max=60)
        return f'[{self.state_border_color}]{label}[/]'

    def _delta_text(self) -> str:
        if self._state == 'background':
            return _status_indicator_markup('background')
        return _status_indicator_markup(
            self._state,
            exit_code=self.exit_code,
            running_tail=self._latest_line() if self._state == 'running' else '',
        )

    def _inline_renderable(self) -> Group:
        return _command_output_preview(self.command, self.output)

    def _inline_widgets(self) -> list[Static]:
        return _terminal_inline_widgets(
            self.command,
            self.output,
            title='Shell',
            state=self._state,
            exit_code=self.exit_code,
        )

    def _refresh_inline_body(self) -> None:
        try:
            chrome = self.query_one('.terminal-chrome', Static)
            command = self.query_one('.terminal-command', Static)
            output = self.query_one('.terminal-output', Static)
        except Exception:
            return
        chrome.update(
            _terminal_chrome('Shell', state=self._state, exit_code=self.exit_code)
        )
        command.update(_command_text(self.command))
        from backend.cli.tui.transcript_typography import TX_BODY_DIM

        output.update(Text((self.output or '').rstrip('\n'), style=TX_BODY_DIM))

    def build_detail_screen(self) -> DetailScreen:
        from backend.cli.tui.screens.detail import ShellDetailScreen

        return ShellDetailScreen(
            command=self.command,
            output=self.output,
            exit_code=self.exit_code,
            cwd=self.cwd,
            is_background=self.is_background,
            kind='Shell',
            heading=_truncate(self.command, 80),
            accent=self.state_border_color,
            title=f'Shell  {_truncate(self.command, 60)}',
        )

    def refresh_summary(self) -> None:
        if self._state in ('running', 'background'):
            self._refresh_line()

    @property
    def wants_periodic_refresh(self) -> bool:
        return self._state == 'running' and not self.output.strip()

    def refresh_animation(self) -> None:
        super().refresh_animation()
        try:
            chrome = self.query_one('.terminal-chrome', Static)
        except Exception:
            return
        chrome.update(
            _terminal_chrome('Shell', state=self._state, exit_code=self.exit_code)
        )


# ── TerminalCard ───────────────────────────────────────────────────────


class TerminalCard(ScanLineCard):
    """Terminal interaction — one transcript card per agent command.

    The exact command and complete session output are always visible.
    """

    def __init__(
        self,
        session_id: str = '',
        session_label: str = '',
        cwd: str = '',
        command: str = '',
        scrollback: str = '',
        *,
        exit_code: int | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.session_id = session_id
        self.session_label = session_label or session_id
        self.cwd = cwd
        self.command = command
        self.scrollback = scrollback
        self.exit_code = exit_code
        self._apply_initial_state()

    @property
    def has_detail(self) -> bool:
        """The complete session output already lives in the transcript."""
        return False

    def _apply_initial_state(self) -> None:
        if self.exit_code == 0:
            self.set_state('done')
        elif self.exit_code is not None:
            self.set_state('failed')
        else:
            self.set_state('running')

    def _latest_line(self) -> str:
        if not self.scrollback:
            return '…'
        lines = self.scrollback.strip().split('\n')
        return _truncate(lines[-1].strip(), 55)

    def _line_text(self) -> str:
        loc = f'{self.session_label} @ {self.cwd}' if self.cwd else self.session_label
        return self._scan_summary_line(
            _scan_label_with_icon('Terminal'), loc, detail_max=55
        )

    def _delta_text(self) -> str:
        return _status_indicator_markup(
            self._state,
            exit_code=self.exit_code,
            running_tail=self._latest_line() if self._state == 'running' else '',
        )

    def _inline_renderable(self) -> Group:
        command = self.command or '(interactive session)'
        return _command_output_preview(command, self.scrollback)

    def _inline_widgets(self) -> list[Static]:
        command = self.command or '(interactive session)'
        title = self.session_label or 'Terminal'
        return _terminal_inline_widgets(
            command,
            self.scrollback,
            title=title,
            state=self._state,
            exit_code=self.exit_code,
        )

    def _refresh_inline_body(self) -> None:
        try:
            chrome = self.query_one('.terminal-chrome', Static)
            command = self.query_one('.terminal-command', Static)
            output = self.query_one('.terminal-output', Static)
        except Exception:
            return
        chrome.update(
            _terminal_chrome(
                self.session_label or 'Terminal',
                state=self._state,
                exit_code=self.exit_code,
            )
        )
        command.update(_command_text(self.command or '(interactive session)'))
        from backend.cli.tui.transcript_typography import TX_BODY_DIM

        output.update(Text((self.scrollback or '').rstrip('\n'), style=TX_BODY_DIM))

    def build_detail_screen(self) -> DetailScreen:
        from backend.cli.tui.screens.detail import TerminalDetailScreen

        loc = f'{self.session_label} @ {self.cwd}' if self.cwd else self.session_label
        return TerminalDetailScreen(
            session_id=self.session_id,
            command=self.command,
            scrollback=self.scrollback,
            cwd=self.cwd,
            exit_code=self.exit_code,
            kind='Terminal',
            heading=_truncate(loc, 80),
            accent=self.state_border_color,
            title=f'Terminal  {self.session_label}',
        )

    def refresh_summary(self) -> None:
        if self._state == 'running':
            self._refresh_line()

    @property
    def wants_periodic_refresh(self) -> bool:
        return self._state == 'running' and not self.scrollback.strip()

    def refresh_animation(self) -> None:
        super().refresh_animation()
        try:
            chrome = self.query_one('.terminal-chrome', Static)
        except Exception:
            return
        chrome.update(
            _terminal_chrome(
                self.session_label or 'Terminal',
                state=self._state,
                exit_code=self.exit_code,
            )
        )


# ── BrowserCard ────────────────────────────────────────────────────────


class BrowserCard(ScanLineCard):
    """Browser action with current activity/result context visible inline."""

    def __init__(
        self,
        domain: str = '',
        action: str = '',
        *,
        full_url: str = '',
        actions: list[str] | None = None,
        extracted: str = '',
        links: list[str] | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.domain = domain
        self.action = action
        self.full_url = full_url
        self._actions = actions  # list of action descriptions
        self.extracted = extracted
        self.links = links
        self._apply_initial_state()

    def _apply_initial_state(self) -> None:
        if self.extracted:
            self.set_state('done')
        else:
            self.set_state('running')

    def _line_text(self) -> str:
        dom = self.domain or '…'
        return self._scan_summary_line(
            _scan_label_with_icon('Browser'), dom, detail_max=40
        )

    def _delta_text(self) -> str:
        if self._state == 'running':
            return _status_indicator_markup(
                'running',
                running_tail=self.action or '…',
            )
        if self._state == 'done':
            tail = _truncate(self.action or '', 40)
            if tail:
                return f'[#e2e8f0]{tail}[/]  {_status_indicator_markup("done")}'
            return _status_indicator_markup('done')
        return _status_indicator_markup(self._state)

    def _inline_renderable(self) -> Group | None:
        parts: list[str] = []
        if self.full_url:
            parts.append(self.full_url)
        if self.action:
            parts.append(self.action)
        if self.extracted:
            parts.append(self.extracted)
        return _payload_preview('\n'.join(parts), label='Browser')

    def build_detail_screen(self) -> DetailScreen:
        from backend.cli.tui.screens.detail import BrowserDetailScreen

        return BrowserDetailScreen(
            full_url=self.full_url,
            actions=self._actions,
            extracted=self.extracted,
            links=self.links,
            kind='Browser',
            heading=self.domain or '…',
            accent=self.state_border_color,
            title=f'Browser  {self.domain}',
        )

    def refresh_summary(self) -> None:
        if self._state == 'running':
            self._refresh_line()

    @property
    def wants_periodic_refresh(self) -> bool:
        return self._state == 'running' and not self.action.strip()


# ── DebuggerCard ───────────────────────────────────────────────────────


class DebuggerCard(ScanLineCard):
    """Debugger state with a bounded stack/locals preview inline."""

    def __init__(
        self,
        location: str = '',
        function: str = '',
        *,
        stack: list[str] | None = None,
        variables: list[tuple[str, str]] | None = None,
        current_frame_index: int = 0,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.location = location
        self.function = function
        self._stack = stack
        self._variables = variables
        self._current_frame_index = current_frame_index
        self._apply_initial_state()

    def _apply_initial_state(self) -> None:
        if self._stack or self._variables:
            self.set_state('done')
        else:
            self.set_state('running')

    def _line_text(self) -> str:
        loc = self.location or '…'
        return self._scan_summary_line(
            _scan_label_with_icon('Debug'), loc, detail_max=80
        )

    def _delta_text(self) -> str:
        fn = self.function or '…'
        if self._state == 'running':
            return _status_indicator_markup('running', running_tail=fn)
        if self._state == 'done':
            tail = _truncate(fn, 30)
            if tail and tail != '…':
                return f'[#e2e8f0]{tail}[/]  {_status_indicator_markup("done")}'
            return _status_indicator_markup('done')
        return _status_indicator_markup(self._state)

    def _inline_renderable(self) -> Group | None:
        lines: list[str] = []
        if self._stack:
            lines.append('Stack')
            lines.extend(str(frame) for frame in self._stack[:4])
        if self._variables:
            lines.append('Locals')
            lines.extend(f'{name} = {value}' for name, value in self._variables[:4])
        return _payload_preview('\n'.join(lines), label='Debugger')

    def build_detail_screen(self) -> DetailScreen:
        from backend.cli.tui.screens.detail import DebuggerDetailScreen

        return DebuggerDetailScreen(
            stack=self._stack,
            variables=self._variables,
            current_frame_index=self._current_frame_index,
            kind='Debugger',
            heading=self.location or '…',
            accent=self.state_border_color,
            title=f'Debugger  {self.location}',
        )

    def refresh_summary(self) -> None:
        if self._state == 'running':
            self._refresh_line()

    @property
    def wants_periodic_refresh(self) -> bool:
        return self._state == 'running' and not self.function.strip()


# ── DelegateCard ───────────────────────────────────────────────────────


class DelegateCard(ScanLineCard):
    """Delegated worker summary with a bounded result visible inline."""

    def __init__(
        self,
        task: str,
        *,
        worker: str = '',
        result: str = '',
        success: bool | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._delegate_task = task
        self._worker = worker
        self._result = result
        self._apply_state(success)

    def _apply_state(self, success: bool | None) -> None:
        if success is None:
            self.set_state('running')
        elif success:
            self.set_state('done')
        else:
            self.set_state('failed')

    def complete(self, *, result: str, success: bool, worker: str = '') -> None:
        self._result = result
        if worker:
            self._worker = worker
        self._apply_state(success)

    def _line_text(self) -> str:
        return self._scan_summary_line(
            _scan_label_with_icon('Delegated'), self._delegate_task, detail_max=70
        )

    def _delta_text(self) -> str:
        if self._state == 'running':
            tail = self._worker or 'worker'
            return _status_indicator_markup('running', running_tail=tail)
        if self._state == 'done':
            return _status_indicator_markup('done')
        return _status_indicator_markup('failed')

    def _inline_renderable(self) -> Group:
        preview = _payload_preview(self._result, label='Worker result')
        if preview is not None:
            return preview
        from backend.cli.tui.transcript_typography import TX_BODY_DIM

        return Group(
            _section_label('Worker'),
            Text(self._worker or 'Working…', style=TX_BODY_DIM),
        )

    def build_detail_screen(self) -> DetailScreen:
        from backend.cli.tui.screens.detail.payload import PayloadDetailScreen

        return PayloadDetailScreen(
            kind='Delegate',
            heading=_truncate(self._delegate_task, 80),
            body=self._result or '(worker is still running)',
            meta_parts=[self._worker] if self._worker else None,
            accent=self.state_border_color,
            title='Delegated work',
        )


# ── MCPCard ────────────────────────────────────────────────────────────


class MCPCard(ScanLineCard):
    """MCP tool call with arguments and a bounded result visible inline."""

    def __init__(
        self,
        name: str,
        *,
        arguments: dict | None = None,
        result: str = '',
        success: bool | None = None,
        meta_lines: list[str] | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._name = name
        self._arguments = dict(arguments or {})
        self._result = result
        self._meta_lines = list(meta_lines or [])
        self._apply_state(success)

    def _args_summary(self) -> str:
        if not self._arguments:
            return self._name
        args_preview = ', '.join(
            f'{key}={repr(value)[:30]}'
            for key, value in list(self._arguments.items())[:2]
        )
        if len(args_preview) > 60:
            args_preview = args_preview[:57] + '...'
        return f'{self._name}({args_preview})' if args_preview else self._name

    def _apply_state(self, success: bool | None) -> None:
        if success is None:
            self.set_state('running')
        elif success:
            self.set_state('done')
        else:
            self.set_state('failed')

    def complete(
        self,
        *,
        result: str,
        success: bool,
        meta_lines: list[str] | None = None,
    ) -> None:
        self._result = result
        if meta_lines:
            self._meta_lines = list(meta_lines)
        self._apply_state(success)

    def _line_text(self) -> str:
        return self._scan_summary_line(
            _scan_label_with_icon('Called'), self._args_summary(), detail_max=70
        )

    def _delta_text(self) -> str:
        if self._state == 'running':
            return _status_indicator_markup('running', running_tail=self._name)
        if self._state == 'done':
            preview = _truncate(self._result.replace('\n', ' '), 36)
            if preview:
                return f'[#9aa8b8]{preview}[/]  {_status_indicator_markup("done")}'
            return _status_indicator_markup('done')
        return _status_indicator_markup('failed')

    def _arguments_text(self) -> str:
        if not self._arguments:
            return ''
        return json.dumps(self._arguments, indent=2, ensure_ascii=False, default=str)

    def _inline_renderable(self) -> Group:
        from backend.cli.tui.transcript_typography import TX_BODY_DIM

        renderables: list[Any] = []
        arguments = self._arguments_text()
        if arguments:
            args_preview, args_hidden = _bounded_text(arguments, max_lines=4)
            renderables.extend(
                (_section_label('Arguments'), Text(args_preview, style=TX_BODY_DIM))
            )
            omitted = _hidden_lines_text(args_hidden)
            if omitted is not None:
                renderables.append(omitted)
        result = _payload_preview(self._result, label='Result')
        if result is not None:
            renderables.append(result)
        elif not renderables:
            renderables.extend(
                (_section_label('Result'), Text('Waiting…', style=TX_BODY_DIM))
            )
        return Group(*renderables)

    def build_detail_screen(self) -> DetailScreen:
        from backend.cli.tui.screens.detail.payload import PayloadDetailScreen

        arguments = self._arguments_text()
        sections: list[str] = []
        if arguments:
            sections.append(f'Arguments\n\n```json\n{arguments}\n```')
        if self._result:
            sections.append(f'Result\n\n{self._result}')
        return PayloadDetailScreen(
            kind='Tool',
            heading=self._name,
            body='\n\n'.join(sections) or '(tool is still running)',
            meta_parts=self._meta_lines,
            accent=self.state_border_color,
            title=f'Tool  {self._name}',
        )


# ── PayloadCard ────────────────────────────────────────────────────────


class PayloadCard(ScanLineCard):
    """Generic artifact row with a bounded inline transcript payload."""

    def __init__(
        self,
        label: str,
        detail: str,
        body: str,
        *,
        success: bool = True,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._label = label
        self._detail = detail
        self._body = body
        self.set_state('done' if success else 'failed')

    def _line_text(self) -> str:
        return self._scan_summary_line(
            _scan_label_with_icon(self._label), self._detail, detail_max=70
        )

    def _delta_text(self) -> str:
        return _status_indicator_markup(self._state)

    def _inline_renderable(self) -> Group | None:
        return _payload_preview(self._body)

    def build_detail_screen(self) -> DetailScreen:
        from backend.cli.tui.screens.detail.payload import PayloadDetailScreen

        return PayloadDetailScreen(
            kind=self._label,
            heading=self._detail,
            body=self._body,
            accent=self.state_border_color,
            title=f'{self._label}  {_truncate(self._detail, 60)}',
        )


# ── CompactionCard ─────────────────────────────────────────────────────


class CompactionCard(ScanLineCard):
    """Context compaction with a bounded summary visible inline."""

    def __init__(self, *, summary: str = '', id: str | None = None) -> None:
        super().__init__(id=id)
        self.summary = summary
        # Live detail screen push: when a screen is opened from this card it
        # registers itself here so streaming updates can re-render the body.
        self._live_detail_screen: Any | None = None
        if summary:
            self.set_state('done')
        else:
            self.set_state('running')

    @property
    def _label(self) -> str:
        return 'Compacted' if self._state == 'done' else 'Compacting'

    def complete(self, *, summary: str) -> None:
        self.summary = summary
        self.set_state('done')
        self._push_summary_to_live_screen()

    def update_summary_streaming(self, text: str) -> None:
        """Update the streaming summary in place.

        Called by the renderer as ``StreamingChunkAction`` events with
        ``tool_call_name='compaction'`` arrive. The card stays in the
        ``running`` state while text is streaming and refreshes the 1-line
        preview, then the open detail screen (if any) is re-poked.
        """
        if not text:
            return
        self.summary = text
        if self._state == 'done':
            return
        self._refresh_line()
        self._push_summary_to_live_screen()

    def _push_summary_to_live_screen(self) -> None:
        screen = getattr(self, '_live_detail_screen', None)
        if screen is None:
            return
        set_body = getattr(screen, 'set_body', None)
        if callable(set_body):
            try:
                set_body(self.summary or '(no summary)')
            except Exception:  # noqa: BLE001
                pass

    def _line_text(self) -> str:
        return self._scan_summary_line(
            _scan_label_with_icon(self._label), '', detail_max=50
        )

    def _delta_text(self) -> str:
        return _status_indicator_markup(self._state)

    def _inline_renderable(self) -> Group:
        preview = _payload_preview(self.summary, label='Summary')
        if preview is not None:
            return preview
        from backend.cli.tui.transcript_typography import TX_BODY_DIM

        return Group(
            _section_label('Summary'),
            Text('Building summary…', style=TX_BODY_DIM),
        )

    def refresh_summary(self) -> None:
        if self._state == 'running':
            self._refresh_line()

    @property
    def wants_periodic_refresh(self) -> bool:
        return self._state == 'running'

    def build_detail_screen(self) -> DetailScreen:
        from backend.cli.tui.screens.detail.payload import PayloadDetailScreen

        screen = PayloadDetailScreen(
            kind='Compaction',
            heading=self._label,
            body=self.summary or '(no summary)',
            accent=self.state_border_color,
            title='Compaction',
        )
        # Register the screen so subsequent streaming updates can
        # re-render its body in real time. The screen clears this back
        # pointer in its on_unmount handler.
        self._live_detail_screen = screen
        return screen


# ── TaskStateCard ─────────────────────────────────────────────────────


class TaskStateCard(ScanLineCard):
    """Structured task-state update rendered without raw serialization."""

    @property
    def has_detail(self) -> bool:
        return False

    def __init__(
        self,
        command: str,
        *,
        revision: int | None = None,
        objective: str = '',
        tasks: list[dict[str, Any]] | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._command = str(command or 'view').strip().lower()
        self._revision = revision
        self._objective = objective.strip()
        self._tasks = list(tasks or [])
        self.set_state('done')

    @staticmethod
    def _normalized_status(task: dict[str, Any]) -> str:
        status = str(task.get('status') or 'todo').strip().lower()
        aliases = {
            'pending': 'todo',
            'completed': 'done',
            'running': 'in_progress',
            'cancelled': 'skipped',
            'canceled': 'skipped',
        }
        return aliases.get(status, status)

    @classmethod
    def _status_text(cls, task: dict[str, Any]) -> Text:
        status = cls._normalized_status(task)
        colors = {
            'todo': '#6f83aa',
            'in_progress': NAVY_RUNNING,
            'done': '#639922',
            'blocked': '#eacb8a',
            'skipped': '#54597b',
        }
        icons = {
            'todo': _glyph('○'),
            'in_progress': _glyph('●'),
            'done': _glyph('✓'),
            'blocked': _glyph('⚠'),
            'skipped': _glyph('·'),
        }
        description = _task_description(task)
        task_id = str(task.get('id') or '').strip()
        rendered = Text()
        rendered.append(f'{icons.get(status, _glyph("•"))} ', style=colors.get(status))
        if task_id:
            rendered.append(f'{task_id} ', style='#6f83aa')
        rendered.append(description, style='#c8d4e8')
        if status == 'blocked':
            reason = _task_blocked_reason(task)
            if reason:
                rendered.append(f' — {reason}', style='#eacb8a')
        return rendered

    def _progress(self) -> tuple[int, int]:
        total = len(self._tasks)
        done = sum(1 for task in self._tasks if self._normalized_status(task) == 'done')
        return done, total

    def _line_text(self) -> str:
        done, total = self._progress()
        detail_parts: list[str] = []
        if total:
            detail_parts.append(f'{done}/{total} complete')
        if self._revision is not None:
            detail_parts.append(f'revision {self._revision}')
        detail = ' · '.join(detail_parts) or self._command.replace('_', ' ')
        return self._scan_summary_line(
            _scan_label_with_icon('Tasks'),
            detail,
            detail_max=70,
        )

    def _delta_text(self) -> str:
        return _status_indicator_markup('done')

    def _inline_renderable(self) -> Group:
        from backend.cli.tui.transcript_typography import TX_BODY_DIM

        renderables: list[Any] = []
        if self._objective:
            renderables.extend(
                (
                    _section_label('Objective'),
                    Text(self._objective, style=TX_BODY_DIM),
                )
            )
        if self._tasks:
            renderables.append(_section_label('Plan'))
            renderables.extend(self._status_text(task) for task in self._tasks)
        if not renderables:
            renderables.append(Text('No tasks recorded.', style=TX_BODY_DIM))
        return Group(*renderables)


# ── AcceptanceCriteriaCard ───────────────────────────────────────────────


class AcceptanceCriteriaCard(ScanLineCard):
    """Acceptance criteria with a bounded checklist visible inline."""

    _VERBS: dict[str, str] = {
        'view': 'Viewed',
        'update': 'Defined',
        'append': 'Updated',
        'audit': 'Audited',
    }

    def __init__(
        self,
        command: str,
        *,
        criteria_list: list[dict[str, Any]] | None = None,
        status_message: str = '',
        success: bool | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._command = str(command or 'view').strip().lower()
        self._criteria_list = list(criteria_list or [])
        self._status_message = status_message
        if success is None:
            self.set_state('running')
        elif success:
            self.set_state('done')
        else:
            self.set_state('failed')

    def complete(
        self,
        *,
        criteria_list: list[dict[str, Any]] | None = None,
        status_message: str = '',
        success: bool = True,
    ) -> None:
        if criteria_list is not None:
            self._criteria_list = list(criteria_list)
        if status_message:
            self._status_message = status_message
        self.set_state('done' if success else 'failed')
        self._refresh_line()

    def _command_verb(self) -> str:
        return self._VERBS.get(self._command, 'Criteria')

    def _detail_summary(self) -> str:
        count = len(self._criteria_list)
        if count:
            label = 'criterion' if count == 1 else 'criteria'
            return f'{count} {label}'
        if self._status_message:
            return _truncate(self._status_message, 70)
        return self._command

    def _line_text(self) -> str:
        return self._scan_summary_line(
            _scan_label_with_icon(self._command_verb()),
            self._detail_summary(),
            detail_max=70,
        )

    def _delta_text(self) -> str:
        return _status_indicator_markup(self._state)

    def _criterion_row(self, item: dict[str, Any]) -> Text | None:
        assertion = _criterion_assertion(item)
        if not assertion:
            return None
        satisfied = item.get('satisfied')
        icon = _glyph('✓') if satisfied is True else _glyph('○')
        color = '#639922' if satisfied is True else '#c8d4e8'
        return Text(f'{icon} {assertion}', style=color)

    def _inline_renderable(self) -> Group:
        from backend.cli.tui.transcript_typography import TX_BODY_DIM

        renderables: list[Any] = [
            row
            for item in self._criteria_list[:8]
            if (row := self._criterion_row(item)) is not None
        ]
        hidden = len(self._criteria_list) - min(len(self._criteria_list), 8)
        if hidden:
            renderables.append(
                Text(
                    f'… {hidden} more {"criteria" if hidden != 1 else "criterion"}',
                    style='#54597b',
                )
            )
        if not renderables:
            message = self._status_message or 'Waiting for criteria…'
            renderables.append(Text(message, style=TX_BODY_DIM))
        return Group(*renderables)

    def build_detail_screen(self) -> DetailScreen:
        from backend.cli.tui.screens.detail.acceptance_criteria import (
            AcceptanceCriteriaDetailScreen,
        )

        fallback = ''
        if not self._criteria_list and self._status_message:
            fallback = self._status_message
        return AcceptanceCriteriaDetailScreen(
            command=self._command,
            criteria_list=self._criteria_list,
            status_message=self._status_message,
            fallback_body=fallback,
            accent=self.state_border_color,
            title=f'Criteria  {self._command_verb()}',
        )
