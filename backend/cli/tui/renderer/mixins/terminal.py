"""RendererTerminalMixin: scan-line shell and terminal transcript cards."""

from __future__ import annotations

from collections import deque
from typing import Any


class RendererTerminalMixin:
    """Scan-line shell/terminal cards and session scrollback buffers.

    Initialisation helpers (called from ``TUIRenderer.__init__`` or
    ``clear_history``) live in :meth:`_init_terminal_state`.
    """

    @classmethod
    def _init_terminal_state(cls, instance: Any) -> None:
        instance._terminal_scrollback_by_session: dict[str, list[str]] = {}
        instance._pending_terminal_scan_cards: dict[str, Any] = {}
        instance._pending_terminal_scan_card: Any | None = None
        if not hasattr(instance, '_pending_shell_cards_by_command'):
            instance._pending_shell_cards_by_command: dict[str, deque[Any]] = {}

    def _remember_terminal_command(self, session_id: str, command: str) -> None:
        """Remember the most relevant command for a terminal session."""
        from backend.cli.tui.helpers import _sanitize_terminal_display_text

        clean_command = _sanitize_terminal_display_text(command or '').strip()
        if not clean_command:
            return
        if session_id:
            self._terminal_commands_by_session[session_id] = clean_command
            if self._pending_terminal_command == clean_command:
                self._pending_terminal_command = None
            return
        self._pending_terminal_command = clean_command

    def _resolve_terminal_command(self, session_id: str = '') -> str | None:
        """Resolve the active command for a terminal session, if known."""
        if session_id:
            command = self._terminal_commands_by_session.get(session_id)
            if command:
                return command
            if self._pending_terminal_command:
                command = self._pending_terminal_command
                self._terminal_commands_by_session[session_id] = command
                self._pending_terminal_command = None
                return command
            return None
        return self._pending_terminal_command

    @staticmethod
    def _terminal_session_label(session_id: str) -> str | None:
        """Format the session label used in terminal card secondary text."""
        return f'session {session_id}' if session_id else None

    # ── scan-line shell card ──────────────────────────────────────────

    def _create_shell_scan_card(self, command: str) -> Any:
        from backend.cli.tui.widgets.scan_line import ShellCard

        self.commit_live_thinking()
        card = ShellCard(command=command)
        card.set_state('running')
        self._pending_shell_cards_by_command[command].append(card)
        self._append_scan_line_card(card)
        return card

    def _complete_shell_scan_card(
        self,
        command: str,
        *,
        output: str,
        exit_code: int | None,
        cwd: str | None = None,
    ) -> None:
        queue = self._pending_shell_cards_by_command.get(command)
        card = queue.popleft() if queue else None
        if queue is not None and not queue:
            self._pending_shell_cards_by_command.pop(command, None)

        if card is None:
            from backend.cli.tui.widgets.scan_line import ShellCard

            card = ShellCard(
                command=command,
                output=output,
                exit_code=exit_code,
                cwd=cwd or '',
            )
            self._append_scan_line_card(card)
            return

        card.output = output
        card.exit_code = exit_code
        card.cwd = cwd or card.cwd
        if exit_code == 0:
            card.set_state('done')
        elif exit_code is not None:
            card.set_state('failed')
        else:
            card.set_state('done')
        card._refresh_line()

    # ── scan-line terminal card ───────────────────────────────────────

    def _create_terminal_scan_card(
        self,
        session_id: str,
        session_label: str,
        cwd: str,
        command: str,
    ) -> Any:
        from backend.cli.tui.widgets.scan_line import TerminalCard

        self.commit_live_thinking()
        card = TerminalCard(
            session_id=session_id,
            session_label=session_label,
            cwd=cwd,
            command=command,
        )
        card.set_state('running')
        self._pending_terminal_scan_card = card
        if session_id:
            self._pending_terminal_scan_cards[session_id] = card
        self._append_scan_line_card(card)
        return card

    def _complete_terminal_scan_card(
        self,
        card: Any,
        *,
        session_id: str = '',
        session_label: str = '',
        cwd: str = '',
        command: str = '',
        scrollback: str = '',
        exit_code: int | None = None,
    ) -> None:
        if card is None:
            return
        card.session_id = session_id or card.session_id
        card.session_label = session_label or card.session_label
        card.cwd = cwd or card.cwd
        card.command = command or card.command
        card.scrollback = scrollback or card.scrollback
        card.exit_code = exit_code
        if exit_code == 0:
            card.set_state('done')
        elif exit_code is not None:
            card.set_state('failed')
        else:
            card.set_state('running')
        card._refresh_line()

    # ── scrollback buffer ────────────────────────────────────────────

    def _accumulate_terminal_scrollback(
        self, session_id: str, content: str
    ) -> None:
        if not content:
            return
        buffers = getattr(self, '_terminal_scrollback_by_session', None)
        if buffers is None:
            self._init_terminal_state(self)
            buffers = self._terminal_scrollback_by_session
        if session_id not in buffers:
            buffers[session_id] = []
        buffers[session_id].append(content)

        card = self._pending_terminal_scan_cards.get(session_id)
        if card is None:
            card = self._pending_terminal_scan_card
        if card is None:
            return
        card.scrollback = '\n'.join(buffers[session_id])
        if card._state == 'running':
            card._refresh_line()

    # ── browser scan-line helpers ───────────────────────────────────

    @staticmethod
    def _extract_browser_domain(url: str) -> str:
        from urllib.parse import urlparse

        parsed = urlparse(url or '')
        return parsed.netloc or parsed.path or url or '?'

    def _create_browser_scan_card(
        self,
        *,
        action: str = '',
        domain: str = '',
        full_url: str = '',
    ) -> Any:
        from backend.cli.tui.widgets.scan_line import BrowserCard

        self.commit_live_thinking()
        card = BrowserCard(
            domain=domain,
            action=action,
            full_url=full_url,
        )
        card.set_state('running')
        self._append_scan_line_card(card)
        return card
