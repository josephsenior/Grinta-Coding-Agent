"""Embedded terminal pane helpers for ActivityCard."""

from __future__ import annotations

from textual.containers import Container

from backend.cli.tui.helpers import infer_display_shell_kind
from backend.cli.tui.widgets.terminal_pane import TerminalPane


class ActivityCardTerminalMixin:
    """Shell/terminal/debugger card behavior."""

    _badge_category: str
    _detail: str
    _outcome: str | None
    _extra_content: str | None
    _terminal_command: str
    _shell_kind: str
    _terminal_cwd: str | None
    _terminal_session_id: str
    _terminal_exit_code: int | None
    _terminal_pane: TerminalPane | None
    _output_tail: str
    _collapsed: bool
    processing: bool

    @staticmethod
    def _command_from_detail(detail: str) -> str:
        text = (detail or '').strip()
        if text.startswith('$ '):
            return text[2:].strip()
        return text

    def _default_shell_kind(self) -> str:
        if self._badge_category == 'terminal':
            return 'terminal'
        if self._badge_category == 'debugger':
            return 'debugger'
        if self._badge_category == 'shell':
            return infer_display_shell_kind(self._terminal_command)
        return 'bash'

    def _is_terminal_card(self) -> bool:
        return self._badge_category in {'shell', 'terminal', 'debugger'}

    def _sync_running_class(self) -> None:
        if not self._is_terminal_card():
            return
        if self.processing:
            self.add_class('-running')
        else:
            self.remove_class('-running')

    def _refresh_output_tail(self) -> None:
        if not self._is_terminal_card():
            return
        lines = [
            line for line in (self._extra_content or '').splitlines() if line.strip()
        ]
        self._output_tail = lines[-1][:100] if lines else ''

    def configure_terminal(
        self,
        *,
        command: str | None = None,
        cwd: str | None = None,
        session_id: str | None = None,
        shell_kind: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        """Update embedded terminal chrome metadata."""
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
        if self._terminal_pane is not None and self.is_mounted:
            self._apply_terminal_pane_state(self._terminal_pane)

    def _terminal_footer_text(self) -> str:
        parts: list[str] = []
        if self._terminal_cwd:
            parts.append(f'cwd: {self._terminal_cwd}')
        if self._terminal_exit_code is not None:
            parts.append(f'exit {self._terminal_exit_code}')
        elif self.processing:
            parts.append('running')
        if self._outcome and self._terminal_exit_code is None:
            parts.append(self._outcome)
        return ' · '.join(parts)

    def _ensure_terminal_pane(self, body: Container) -> TerminalPane:
        if self._terminal_pane is not None:
            return self._terminal_pane
        try:
            pane = body.query_one('#terminal-pane', TerminalPane)
            self._terminal_pane = pane
            self._apply_terminal_pane_state(pane)
            return pane
        except Exception:
            pass
        pane = TerminalPane(
            shell_kind=self._shell_kind,
            command=self._terminal_command,
            cwd=self._terminal_cwd,
            session_id=self._terminal_session_id,
            footer=self._terminal_footer_text(),
            exit_code=self._terminal_exit_code,
            running=self.processing,
            id='terminal-pane',
        )
        body.remove_children()
        body.mount(pane)
        self._terminal_pane = pane
        self._apply_terminal_pane_state(pane)
        return pane

    def _apply_terminal_pane_state(self, pane: TerminalPane) -> None:
        pane.set_shell_kind(self._shell_kind)
        pane.set_command(self._terminal_command)
        pane.set_cwd(self._terminal_cwd)
        pane.set_session_id(self._terminal_session_id)
        pane.set_exit_code(self._terminal_exit_code)
        pane.set_footer(self._terminal_footer_text())
        pane.set_running(self.processing)
        if self._extra_content:
            pane.set_output(self._extra_content)

    def _mount_terminal_body(self, body: Container) -> None:
        pane = self._ensure_terminal_pane(body)
        pane.set_output(self._extra_content or '')
        body.display = not self._collapsed
