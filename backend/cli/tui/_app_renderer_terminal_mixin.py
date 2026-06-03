"""_AppRendererTerminalMixin: terminal command cards (per-session)."""

from __future__ import annotations

from typing import Any

from backend.cli._event_renderer.unified_renderer import (
    ActivityRenderer,
)
from backend.cli.tui._app_helpers import (
    _sanitize_terminal_display_text,
)


class _AppRendererTerminalMixin:
    """terminal command cards (per-session)."""

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
        collapse_after_update: bool = False,
    ) -> None:
        session_key = session_id or 'terminal'
        widget = self._terminal_cards_by_session.get(session_key)
        if widget is None and session_id and self._pending_terminal_card is not None:
            widget = self._pending_terminal_card
            self._terminal_cards_by_session[session_key] = widget
            self._pending_terminal_card = None
        if widget is None:
            card = ActivityRenderer.terminal_action(
                verb,
                detail,
                secondary=secondary,
                secondary_kind=secondary_kind,
                extra_content=extra_content,
            )
            widget = self._write_card(card, collapsed=True)
            if session_id:
                self._terminal_cards_by_session[session_key] = widget
            else:
                self._pending_terminal_card = widget
            return

        # Update existing widget for same session
        widget.set_verb(verb, detail=detail)
        widget.set_status(
            'ok'
            if secondary_kind == 'ok'
            else 'err'
            if secondary_kind == 'err'
            else 'neutral',
            outcome=secondary,
        )
        if extra_content:
            widget.append_content(extra_content)

        del collapse_after_update

        widget.set_processing(processing)
        if processing:
            self._clear_last_active_card_processing()
            widget.set_processing(True)
            self._last_active_card = widget
            self._tui.set_current_operation(
                f'{verb} {detail}'.strip(),
                meta=secondary or f'session {session_key}',
                active=True,
            )
        else:
            if self._last_active_card is widget:
                self._last_active_card = None
            self._tui.set_current_operation(
                f'{verb} {detail}'.strip(),
                meta=secondary or f'session {session_key}',
                active=False,
            )

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

        card = ActivityRenderer.shell_command(
            command, output=output, exit_code=exit_code
        )
        if widget is None:
            self._write_card(card)
            return

        if self._last_active_card is widget:
            self._last_active_card = None

        status = 'ok' if exit_code == 0 else 'err'
        widget.set_status(status, outcome=card.secondary)

        # Build expanded content with metadata header per spec
        meta_lines = [f'$ {command}']
        if cwd:
            meta_lines.append(f'cwd: {cwd}')
        meta_lines.append(f'exit: {exit_code}')
        meta_lines.append('─' * 50)

        extra_parts = list(meta_lines)
        if card.extra_lines:
            for extra in card.extra_lines:
                indent = '  ' * extra.indent
                extra_parts.append(f'{indent}{extra.text}')
        extra_content = '\n'.join(extra_parts)

        widget.update_content(extra_content)
        widget.set_processing(False)
        self._tui.set_current_operation(
            f'{card.verb} {card.detail}'.strip(),
            meta=card.secondary or 'completed',
            active=False,
        )

    def _create_shell_command_card(self, command: str) -> Any:
        from backend.cli.tui.widgets.activity_card import (
            ActivityCard as TUIActivityCard,
        )

        self.commit_live_thinking()
        card = ActivityRenderer.shell_command(command)
        widget = TUIActivityCard(
            verb=card.verb,
            detail=card.detail,
            badge_category=card.badge_category,
            status='running',
            outcome=card.secondary,
            extra_content=None,
            collapsed=True,
            collapsible=True,
        )
        widget.set_processing(True)
        self._clear_last_active_card_processing()
        self._last_active_card = widget
        self._pending_shell_cards_by_command[command].append(widget)
        self._tui.set_current_operation(
            f'{card.verb} {card.detail}'.strip(),
            meta='running',
            active=True,
        )
        display = self._tui._get_display()
        display.append_widget(widget)
        return widget
