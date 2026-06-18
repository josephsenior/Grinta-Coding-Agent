"""Session-tier transcript row: scan header + always-open terminal pane."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Static

from backend.cli.theme import CLR_REASONING_SNAP, NAVY_ERROR, NAVY_READY
from backend.cli.tui.widgets.terminal_pane import TerminalPane

_SESSION_PIPE = '#24385c'
_SESSION_PREFIX = '#5eead4'
_SESSION_TARGET = '#cbd5e1'
_SESSION_DIM = '#54597b'

_STATUS_RESULT_COLOR = {
    'ok': NAVY_READY,
    'err': NAVY_ERROR,
    'warn': NAVY_ERROR,
    'running': _SESSION_PREFIX,
    'neutral': CLR_REASONING_SNAP,
}


class SessionPanel(Container):
    """Session-tier tool row — header scan line plus always-visible output pane."""

    DEFAULT_CSS = """
    SessionPanel {
        width: 100%;
        height: auto;
        margin: 0 0 2 0;
        border: none;
        background: #050913;
        border-left: solid #24385c;
        padding: 0;
    }
    SessionPanel.-running {
        border-left: heavy #5eead4;
    }
    SessionPanel.-category-debugger {
        border-left: solid #24385c;
    }
    SessionPanel .session-header {
        width: 100%;
        height: 1;
        padding: 0 1 0 2;
    }
    SessionPanel .session-body {
        width: 100%;
        height: auto;
        padding: 0;
    }
    """

    is_pinned = False

    def __init__(
        self,
        *,
        verb: str,
        detail: str,
        badge_category: str = 'shell',
        status: str = 'neutral',
        outcome: str | None = None,
        shell_kind: str = 'bash',
        terminal_command: str = '',
        session_id: str = '',
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.add_class(f'category-{badge_category}')
        self._verb = verb
        self._detail = detail
        self._badge_category = badge_category
        self._status = status
        self._outcome = outcome
        self._shell_kind = shell_kind
        self._terminal_command = terminal_command or self._command_from_detail(detail)
        self._terminal_cwd: str | None = None
        self._terminal_session_id = session_id or ''
        self._terminal_exit_code: int | None = None
        self._terminal_pane: TerminalPane | None = None
        self._incremental_mode = False
        self.processing = False
        self._output_buffer = ''

    @staticmethod
    def _command_from_detail(detail: str) -> str:
        text = (detail or '').strip()
        if text.startswith('$ '):
            return text[2:].strip()
        return text

    def should_auto_expand(self) -> bool:
        return False

    def collapse(self) -> None:
        return

    def expand(self) -> None:
        return

    def _family_label(self) -> str:
        if self._badge_category == 'debugger':
            return 'Debugger'
        if self._badge_category == 'terminal':
            return 'Terminal'
        return 'Shell'

    def _header_text(self) -> Text:
        family = self._family_label()
        target = self._detail or self._terminal_command or '…'
        if self.processing:
            result = self._outcome or 'running'
            status_key = 'running'
        else:
            result = self._outcome or ''
            status_key = self._status
        parts: list[tuple[str, str]] = [
            (f'{family}  ', _SESSION_PREFIX),
            (target, _SESSION_TARGET),
        ]
        if result:
            parts.append((' · ', _SESSION_DIM))
            parts.append(
                (result, _STATUS_RESULT_COLOR.get(status_key, CLR_REASONING_SNAP))
            )
        return Text.assemble(*parts)

    def _footer_text(self) -> str:
        parts: list[str] = []
        if self._terminal_cwd:
            parts.append(f'cwd: {self._terminal_cwd}')
        if self._terminal_exit_code is not None:
            parts.append(f'exit {self._terminal_exit_code}')
        elif self.processing:
            parts.append('running')
        elif self._outcome:
            parts.append(self._outcome)
        return ' · '.join(parts)

    def _sync_running_class(self) -> None:
        self.set_class(self.processing, '-running')

    def _refresh_header(self) -> None:
        if not self.is_mounted:
            return
        try:
            self.query_one('.session-header', Static).update(self._header_text())
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        yield Static(self._header_text(), classes='session-header')
        with Vertical(classes='session-body'):
            yield TerminalPane(
                shell_kind=self._shell_kind,
                command=self._terminal_command,
                cwd=self._terminal_cwd,
                session_id=self._terminal_session_id,
                footer=self._footer_text(),
                exit_code=self._terminal_exit_code,
                running=self.processing,
                id='terminal-pane',
            )

    def on_mount(self) -> None:
        self._resolve_pane()
        self._apply_terminal_state()
        self._sync_running_class()

    def _sync_output_to_pane(self) -> None:
        pane = self._resolve_pane()
        if pane is None:
            return
        pane.set_output(self._output_buffer)

    def _resolve_pane(self) -> TerminalPane | None:
        if self._terminal_pane is not None:
            return self._terminal_pane
        if not self.is_mounted:
            return None
        try:
            self._terminal_pane = self.query_one('#terminal-pane', TerminalPane)
        except Exception:
            return None
        return self._terminal_pane

    def set_verb(self, verb: str, *, detail: str | None = None) -> None:
        self._verb = verb
        if detail is not None:
            self._detail = detail
            if detail.strip():
                self._terminal_command = self._command_from_detail(detail)
        self._refresh_header()
        if self._terminal_pane is not None:
            self._terminal_pane.set_command(self._terminal_command)

    def set_status(self, status: str, outcome: str | None = None) -> None:
        self._status = status
        if outcome is not None:
            self._outcome = outcome
        self._refresh_header()
        self._apply_terminal_state()

    def set_processing(self, processing: bool) -> None:
        self.processing = processing
        if processing and self._status == 'neutral':
            self._status = 'running'
        elif not processing and self._status == 'running':
            self._status = 'neutral'
        self._sync_running_class()
        self._refresh_header()
        self._apply_terminal_state()

    def configure_terminal(
        self,
        *,
        command: str | None = None,
        cwd: str | None = None,
        session_id: str | None = None,
        shell_kind: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        if command is not None:
            self._terminal_command = command.strip()
        if cwd is not None:
            self._terminal_cwd = cwd.strip() or None
        if session_id is not None:
            self._terminal_session_id = session_id.strip()
        if shell_kind is not None:
            self._shell_kind = shell_kind
        if exit_code is not None:
            self._terminal_exit_code = exit_code
        self._apply_terminal_state()

    def _apply_terminal_state(self) -> None:
        pane = self._resolve_pane()
        if pane is None:
            return
        pane.set_shell_kind(self._shell_kind)
        pane.set_command(self._terminal_command)
        pane.set_cwd(self._terminal_cwd)
        pane.set_session_id(self._terminal_session_id)
        pane.set_exit_code(self._terminal_exit_code)
        pane.set_footer(self._footer_text())
        pane.set_running(self.processing)
        self._sync_output_to_pane()

    def enable_incremental_mode(self) -> None:
        self._incremental_mode = True

    def update_content(self, extra_content: str) -> None:
        self._output_buffer = extra_content or ''
        self._sync_output_to_pane()

    def append_content_incremental(self, text: str) -> None:
        chunk = (text or '').strip('\n')
        if not chunk:
            return
        if self._output_buffer:
            self._output_buffer += '\n' + chunk
        else:
            self._output_buffer = chunk
        pane = self._resolve_pane()
        if pane is not None:
            pane.append_output(chunk)
