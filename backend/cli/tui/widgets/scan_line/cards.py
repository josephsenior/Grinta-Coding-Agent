"""Concrete ScanLineCard subclasses — one per agent action type.

Each card is exactly 1 line tall with a ``⤢`` detail button.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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


def _status_indicator_markup(
    state: str,
    *,
    exit_code: int | None = None,
    running_tail: str = '',
) -> str:
    """Right-slot status glyph for shell/terminal scan rows."""
    if state == 'running':
        tail = (running_tail or '').strip()
        if tail and tail != '…':
            return f'[#EF9F27]{_truncate(tail, 40)}[/]'
        return '[#EF9F27]…[/]'
    if state == 'background':
        return '[#6B9FD4]detached[/]'
    if state == 'done':
        return '[#639922]✓[/]'
    if state == 'failed':
        if exit_code is not None:
            return f'[#E24B4A]✗ {exit_code}[/]'
        return '[#E24B4A]✗[/]'
    return ''


# One unique icon per scan-line verb — no sharing between card kinds.
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
}


def _scan_label_with_icon(label: str) -> str:
    """Prefix a scan-line verb with its icon when one is defined."""
    icon = _SCAN_LINE_ICONS.get(label, '')
    if not icon:
        return label
    return f'{icon} {label}'


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
    """1-line file edit summary — full diff in detail screen.

    Shared across ``create_file``, ``insert_text``, ``replace_string``,
    ``edit_symbol``, ``multi_edit``, and ``undo_last_edit``.  Only the file
    path + delta appear in the 1-line summary.
    """

    DEFAULT_CSS = """
    EditCard.-edited {
        border-left: solid #91abec;
    }
    EditCard.-edited.failed {
        border-left: solid #E24B4A;
    }
    EditCard.-undone {
        border-left: solid #91abec;
    }
    EditCard.-undone.failed {
        border-left: solid #E24B4A;
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
        verb = self._edit_verb()
        path = _compact_path(self._display_path)
        return self._scan_summary_line(_scan_label_with_icon(verb), path, detail_max=40)

    def _delta_text(self) -> str:
        parts: list[str] = []
        if self._added:
            parts.append(f'[#639922]+{self._added}[/]')
        if self._removed:
            parts.append(f'[#E24B4A]-{self._removed}[/]')
        delta = ' '.join(parts)
        if self._syntax_pass is True:
            status = _status_indicator_markup('done')
        elif self._syntax_pass is False:
            status = _status_indicator_markup('failed')
        else:
            status = ''
        if delta and status:
            return f'{delta}  {status}'
        return delta or status

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
    """1-line shell command summary — full output in detail screen."""

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
        return self._scan_summary_line(
            _scan_label_with_icon('Shell'), self.command, detail_max=50
        )

    def _delta_text(self) -> str:
        if self._state == 'background':
            return _status_indicator_markup('background')
        return _status_indicator_markup(
            self._state,
            exit_code=self.exit_code,
            running_tail=self._latest_line() if self._state == 'running' else '',
        )

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


# ── TerminalCard ───────────────────────────────────────────────────────


class TerminalCard(ScanLineCard):
    """1-line terminal interaction — one card per agent command.

    Summary shows session label + cwd + latest output line.
    Detail shows full session scrollback.
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

    def build_detail_screen(self) -> DetailScreen:
        from backend.cli.tui.screens.detail import TerminalDetailScreen

        loc = f'{self.session_label} @ {self.cwd}' if self.cwd else self.session_label
        return TerminalDetailScreen(
            session_id=self.session_id,
            command=self.command,
            scrollback=self.scrollback,
            cwd=self.cwd,
            exit_code=self.exit_code,
            kind='Term',
            heading=_truncate(loc, 80),
            accent=self.state_border_color,
            title=f'Terminal  {self.session_label}',
        )

    def refresh_summary(self) -> None:
        if self._state == 'running':
            self._refresh_line()


# ── BrowserCard ────────────────────────────────────────────────────────


class BrowserCard(ScanLineCard):
    """1-line browser action summary — full URL + actions in detail."""

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


# ── DebuggerCard ───────────────────────────────────────────────────────


class DebuggerCard(ScanLineCard):
    """1-line debugger state summary — stack + locals in detail."""

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

    def build_detail_screen(self) -> DetailScreen:
        from backend.cli.tui.screens.detail import DebuggerDetailScreen

        return DebuggerDetailScreen(
            stack=self._stack,
            variables=self._variables,
            current_frame_index=self._current_frame_index,
            kind='Debug',
            heading=self.location or '…',
            accent=self.state_border_color,
            title=f'Debugger  {self.location}',
        )

    def refresh_summary(self) -> None:
        if self._state == 'running':
            self._refresh_line()


# ── DelegateCard ───────────────────────────────────────────────────────


class DelegateCard(ScanLineCard):
    """1-line delegated worker summary — full result in detail screen."""

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

    def build_detail_screen(self) -> DetailScreen:
        from backend.cli.tui.screens.detail.payload import PayloadDetailScreen

        meta: list[str] = []
        if self._worker:
            meta.append(f'[#6f83aa]worker: {self._worker}[/]')
        return PayloadDetailScreen(
            kind='Delegate',
            heading=_truncate(self._delegate_task, 80),
            body=self._result,
            meta_parts=meta,
            accent=self.state_border_color,
            title=f'Delegate  {_truncate(self._delegate_task, 60)}',
        )


# ── MCPCard ────────────────────────────────────────────────────────────


class MCPCard(ScanLineCard):
    """1-line MCP tool call — arguments + result in detail screen."""

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

    def build_detail_screen(self) -> DetailScreen:
        from backend.cli.tui.screens.detail.payload import PayloadDetailScreen

        meta = [f'[#6f83aa]{line}[/]' for line in self._meta_lines if line]
        return PayloadDetailScreen(
            kind='MCP',
            heading=self._name,
            body=self._result,
            meta_parts=meta,
            accent=self.state_border_color,
            title=f'MCP  {self._name}',
        )


# ── PayloadCard ────────────────────────────────────────────────────────


class PayloadCard(ScanLineCard):
    """Generic artifact row (thinking code/tool/shared payloads)."""

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

    def build_detail_screen(self) -> DetailScreen:
        from backend.cli.tui.screens.detail.payload import PayloadDetailScreen

        return PayloadDetailScreen(
            kind=self._label,
            heading=_truncate(self._detail, 80),
            body=self._body,
            accent=self.state_border_color,
            title=f'{self._label}  {_truncate(self._detail, 60)}',
        )
