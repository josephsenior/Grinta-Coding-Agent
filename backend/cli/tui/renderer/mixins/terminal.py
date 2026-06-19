"""RendererTerminalMixin: session-tier panels for shell and terminal tools."""

from __future__ import annotations

from typing import Any

from backend.cli.event_rendering.unified_renderer import (
    ActivityRenderer,
)
from backend.cli.tui.helpers import (
    _sanitize_terminal_display_text,
    infer_display_shell_kind,
)
from backend.cli.tui.widgets.session_panel import SessionPanel


class RendererTerminalMixin:
    """Session-tier shell and terminal transcript panels.

    Initialisation helpers (called from ``TUIRenderer.__init__`` or
    ``clear_history``) live in :meth:`_init_terminal_state`.
    """

    @classmethod
    def _init_terminal_state(cls, instance: Any) -> None:
        instance._terminal_scrollback_by_session: dict[str, list[str]] = {}
        instance._pending_terminal_scan_cards: dict[str, Any] = {}
        instance._pending_terminal_scan_card: Any | None = None

    def _remember_terminal_command(self, session_id: str, command: str) -> None:
        """Remember the most relevant command for a terminal session."""
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

    def _terminal_card_detail(self, session_id: str = '', command: str = '') -> str:
        """Build a stable terminal card headline."""
        if command.strip():
            self._remember_terminal_command(session_id, command)
        active_command = self._resolve_terminal_command(session_id)
        if active_command:
            preview = active_command[:80] + ('...' if len(active_command) > 80 else '')
            return f'$ {preview}'
        if session_id:
            return f'session {session_id}'
        return 'terminal session'

    @staticmethod
    def _terminal_session_label(session_id: str) -> str | None:
        """Format the session label used in terminal card secondary text."""
        return f'session {session_id}' if session_id else None

    def _resolve_terminal_widget(self, session_key: str, session_id: str):
        widget = self._terminal_cards_by_session.get(session_key)
        if widget is None and session_id and self._pending_terminal_card is not None:
            widget = self._pending_terminal_card
            self._terminal_cards_by_session[session_key] = widget
            self._pending_terminal_card = None
        return widget

    def _mount_session_panel(self, panel: SessionPanel) -> SessionPanel:
        self._write_session_panel(panel)
        return panel

    def _create_and_write_terminal_card(
        self,
        session_key: str,
        session_id: str,
        verb: str,
        detail: str,
        secondary: str | None,
        secondary_kind: str,
        extra_content: str | None,
    ) -> None:
        del secondary_kind
        command = SessionPanel._command_from_detail(detail)
        panel = SessionPanel(
            verb=verb,
            detail=detail,
            badge_category='terminal',
            status='running' if secondary else 'neutral',
            outcome=secondary,
            shell_kind='terminal',
            terminal_command=command if not command.startswith('session ') else '',
            session_id=session_id,
        )
        panel.set_processing(True)
        panel.enable_incremental_mode()
        if extra_content:
            panel.update_content(extra_content)
        widget = self._mount_session_panel(panel)
        self._activate_activity_card(widget)
        if session_id:
            self._terminal_cards_by_session[session_key] = widget
        else:
            self._pending_terminal_card = widget

    @staticmethod
    def _terminal_status_from_kind(secondary_kind: str) -> str:
        if secondary_kind == 'ok':
            return 'ok'
        if secondary_kind == 'err':
            return 'err'
        return 'neutral'

    def _apply_terminal_processing(
        self,
        widget: Any,
        processing: bool,
        verb: str,
        detail: str,
        secondary: str | None,
        session_key: str,
    ) -> None:
        del verb, detail, session_key
        if processing:
            self._activate_activity_card(widget)
            return

        widget.set_processing(False)
        if self._last_active_card is widget:
            self._last_active_card = None

    def _upsert_terminal_session_card(
        self,
        *,
        session_id: str,
        verb: str,
        detail: str,
        secondary: str | None = None,
        secondary_kind: str = 'neutral',
        extra_content: str | None = None,
        processing: bool = True,
    ) -> None:
        session_key = session_id or 'terminal'
        widget = self._resolve_terminal_widget(session_key, session_id)
        if widget is None:
            self._create_and_write_terminal_card(
                session_key,
                session_id,
                verb,
                detail,
                secondary,
                secondary_kind,
                extra_content,
            )
            return

        widget.set_verb(verb, detail=detail)
        widget.set_status(
            self._terminal_status_from_kind(secondary_kind),
            outcome=secondary,
        )
        command = SessionPanel._command_from_detail(detail)
        if command and not command.startswith('session '):
            widget.configure_terminal(
                command=command,
                session_id=session_id,
                shell_kind='terminal',
            )
        elif session_id:
            widget.configure_terminal(session_id=session_id, shell_kind='terminal')
        if extra_content:
            widget.append_content_incremental(extra_content)

        self._apply_terminal_processing(
            widget,
            processing,
            verb,
            detail,
            secondary,
            session_key,
        )

    def _resolve_shell_panel(self, command: str) -> Any | None:
        queue = self._pending_shell_cards_by_command.get(command)
        if queue:
            return queue[0]
        try:
            from backend.cli.tui.widgets.session_panel import SessionPanel

            display = self._tui._get_display()
            for panel in reversed(list(display.query(SessionPanel))):
                if 'category-shell' not in panel.classes:
                    continue
                if panel._terminal_command == command:
                    return panel
        except Exception:
            return None
        return None

    def _complete_shell_command_card(
        self,
        command: str,
        *,
        output: str,
        exit_code: int | None,
        cwd: str | None = None,
    ) -> None:
        queue = self._pending_shell_cards_by_command.get(command)
        widget = queue.popleft() if queue else None
        if queue is not None and not queue:
            self._pending_shell_cards_by_command.pop(command, None)
        if widget is None:
            widget = self._resolve_shell_panel(command)

        card = ActivityRenderer.shell_command(
            command, output=output, exit_code=exit_code
        )
        if widget is None:
            panel = SessionPanel(
                verb=card.verb,
                detail=card.detail,
                badge_category='shell',
                status='ok' if exit_code == 0 else 'err',
                outcome=card.secondary,
                shell_kind=infer_display_shell_kind(command),
                terminal_command=command,
            )
            panel.configure_terminal(command=command, cwd=cwd, exit_code=exit_code)
            output_text = output or ''
            if not output_text and card.extra_lines:
                output_lines: list[str] = []
                for extra in card.extra_lines:
                    indent = '  ' * extra.indent
                    output_lines.append(f'{indent}{extra.text}')
                output_text = '\n'.join(output_lines)
            panel.update_content(output_text)
            panel.set_processing(False)
            self._mount_session_panel(panel)
            return

        if self._last_active_card is widget:
            self._last_active_card = None

        status = 'ok' if exit_code == 0 else 'err'
        widget.configure_terminal(command=command, cwd=cwd, exit_code=exit_code)

        output_text = output or ''
        if not output_text and card.extra_lines:
            output_lines: list[str] = []
            for extra in card.extra_lines:
                indent = '  ' * extra.indent
                output_lines.append(f'{indent}{extra.text}')
            output_text = '\n'.join(output_lines)

        widget.update_content(output_text)
        widget.set_processing(False)
        widget.set_status(status, outcome=card.secondary)
        return

    def _create_shell_command_card(self, command: str) -> Any:
        self.commit_live_thinking()
        card = ActivityRenderer.shell_command(command)
        panel = SessionPanel(
            verb=card.verb,
            detail=card.detail,
            badge_category='shell',
            status='running',
            outcome=card.secondary,
            shell_kind=infer_display_shell_kind(command),
            terminal_command=command,
        )
        panel.set_processing(True)
        panel.enable_incremental_mode()
        self._activate_activity_card(panel)
        self._pending_shell_cards_by_command[command].append(panel)
        self._mount_session_panel(panel)
        return panel

    # ── scan-line shell card (new 1-line feed) ──────────────────────

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
            # Create a fresh done card if no pending one exists
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

    # ── scan-line terminal card (new 1-line feed) ───────────────────

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
