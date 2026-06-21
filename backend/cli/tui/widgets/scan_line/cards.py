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
    end = content.index('</SYNTAX_CHECK_FAILED>', start) if '</SYNTAX_CHECK_FAILED>' in content[start:] else len(content)
    return content[start:end].strip() or None


def _format_diff_delta(added: int, removed: int) -> str:
    parts: list[str] = []
    if added:
        parts.append(f'+{added}')
    if removed:
        parts.append(f'-{removed}')
    return ' '.join(parts) if parts else '0'


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
        return f'[#5eead4]Agent[/]  [#c8d4e8]{_truncate(self._text, 80)}[/]'

    def build_detail_screen(self) -> DetailScreen:
        from backend.cli.tui.screens.detail import MessageDetailScreen

        return MessageDetailScreen(message_text=self._text)


# ── EditCard ───────────────────────────────────────────────────────────

class EditCard(ScanLineCard):
    """1-line file edit summary — full diff in detail screen.

    Shared across ``create_file``, ``insert_text``, ``replace_string``,
    ``edit_symbol``, and ``multi_edit``.  Only the file path + delta appear
    in the 1-line summary.
    """

    def __init__(
        self,
        display_path: str,
        *,
        added: int = 0,
        removed: int = 0,
        is_create: bool = False,
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
        self._encoded_diff = encoded_diff
        self._syntax_pass = syntax_pass
        self._syntax_error = syntax_error
        self._finalize_state()

    def _finalize_state(self) -> None:
        if self._syntax_pass is False:
            self.set_state('failed')
        elif self._added or self._removed or self._is_create:
            self.set_state('done')
        else:
            self.set_state('done')

    def _line_text(self) -> str:
        verb = 'Created' if self._is_create else 'Edited'
        path = _compact_path(self._display_path)
        badge = ''
        pipe_color = {
            'queued': '#2d4a6a',
            'running': '#EF9F27',
            'done': '#639922',
            'failed': '#E24B4A',
        }.get(self._state, '#2d4a6a')
        if self._syntax_pass is True:
            badge = ' [#639922]✓[/]'
        elif self._syntax_pass is False:
            badge = ' [#E24B4A]✗[/]'
        return f'[{pipe_color}]{verb}[/]  [#c8d4e8]{path}[/]{badge}'

    def _delta_text(self) -> str:
        parts: list[str] = []
        if self._added:
            parts.append(f'[#639922]+{self._added}[/]')
        if self._removed:
            parts.append(f'[#E24B4A]-{self._removed}[/]')
        return ' '.join(parts)

    def build_detail_screen(self) -> DetailScreen:
        from backend.cli.tui.screens.detail import EditDetailScreen

        verb = 'Created' if self._is_create else 'Edited'
        return EditDetailScreen(
            title=f'{verb}  {self._display_path}',
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
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.command = command
        self.output = output
        self.exit_code = exit_code
        self.cwd = cwd
        self._apply_initial_state()

    def _apply_initial_state(self) -> None:
        if self.exit_code == 0:
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
        if self.exit_code == 0:
            return '✓'
        if self.exit_code is not None:
            return f'exit {self.exit_code}'
        return self._latest_line()

    def _line_text(self) -> str:
        cmd = _truncate(self.command, 50)
        label_color = self.state_border_color
        return f'[{label_color}]Shell[/]  [#c8d4e8]{cmd}[/]'

    def _delta_text(self) -> str:
        if self.exit_code == 0:
            return '[#639922]✓[/]'
        if self.exit_code is not None:
            return f'[#E24B4A]exit {self.exit_code}[/]'
        return f'[#EF9F27]{self._latest_line()}[/]'

    def build_detail_screen(self) -> DetailScreen:
        from backend.cli.tui.screens.detail import ShellDetailScreen

        return ShellDetailScreen(
            command=self.command,
            output=self.output,
            exit_code=self.exit_code,
            cwd=self.cwd,
            title=f'Shell  {_truncate(self.command, 60)}',
        )

    def refresh_summary(self) -> None:
        if self._state == 'running':
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
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.session_id = session_id
        self.session_label = session_label or session_id
        self.cwd = cwd
        self.command = command
        self.scrollback = scrollback
        self._apply_initial_state()

    def _apply_initial_state(self) -> None:
        self.set_state('running')

    def _latest_line(self) -> str:
        if not self.scrollback:
            return '…'
        lines = self.scrollback.strip().split('\n')
        return _truncate(lines[-1].strip(), 55)

    def _line_text(self) -> str:
        loc = f'{self.session_label} @ {self.cwd}' if self.cwd else self.session_label
        return f'[#5eead4]Term[/]  [#c8d4e8]{loc}[/]'

    def _delta_text(self) -> str:
        tail = self._latest_line()
        return f'[#e2e8f0]{tail}[/]'

    def build_detail_screen(self) -> DetailScreen:
        from backend.cli.tui.screens.detail import TerminalDetailScreen

        return TerminalDetailScreen(
            session_id=self.session_id,
            command=self.command,
            scrollback=self.scrollback,
            cwd=self.cwd,
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
        return f'[#5eead4]Browser[/]  [#c8d4e8]{dom}[/]'

    def _delta_text(self) -> str:
        act = _truncate(self.action or '…', 40)
        return f'[#e2e8f0]{act}[/]'

    def build_detail_screen(self) -> DetailScreen:
        from backend.cli.tui.screens.detail import BrowserDetailScreen

        return BrowserDetailScreen(
            full_url=self.full_url,
            actions=self._actions,
            extracted=self.extracted,
            links=self.links,
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
        return f'[#5eead4]Debug[/]  [#c8d4e8]{loc}[/]'

    def _delta_text(self) -> str:
        fn = _truncate(self.function or '…', 30)
        return f'[#e2e8f0]{fn}[/]'

    def build_detail_screen(self) -> DetailScreen:
        from backend.cli.tui.screens.detail import DebuggerDetailScreen

        return DebuggerDetailScreen(
            stack=self._stack,
            variables=self._variables,
            current_frame_index=self._current_frame_index,
            title=f'Debugger  {self.location}',
        )

    def refresh_summary(self) -> None:
        if self._state == 'running':
            self._refresh_line()
