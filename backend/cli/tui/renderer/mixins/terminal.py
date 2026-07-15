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
        instance._tool_cards_by_action_id: dict[int, Any] = {}
        instance._tool_kinds_by_action_id: dict[int, str] = {}
        if not hasattr(instance, '_pending_shell_cards_by_command'):
            instance._pending_shell_cards_by_command: dict[str, deque[Any]] = {}
        instance._pending_compaction_scan_card: Any | None = None

    def _resolve_running_compaction_card(self) -> Any | None:
        """Return the pending compaction card, or the newest running one in the transcript."""
        card = getattr(self, '_pending_compaction_scan_card', None)
        if card is not None:
            return card
        try:
            from backend.cli.tui.widgets.scan_line import CompactionCard

            tui = getattr(self, '_tui', None)
            if tui is None:
                return None
            screen = tui if hasattr(tui, 'query') else getattr(tui, 'screen', None)
            query = getattr(screen, 'query', None)
            if not callable(query):
                return None
            for candidate in reversed(list(query(CompactionCard).results())):
                if getattr(candidate, 'state', None) == 'running':
                    return candidate
        except Exception:
            return None
        return None

    def _create_compaction_scan_card(self) -> Any:
        from backend.cli.tui.widgets.scan_line import CompactionCard

        self.commit_live_thinking()
        card = CompactionCard()
        card.set_state('running')
        self._pending_compaction_scan_card = card
        self._append_scan_line_card(card)
        return card

    def _complete_compaction_scan_card(self, *, summary: str) -> None:
        card = self._resolve_running_compaction_card()
        self._pending_compaction_scan_card = None

        if card is None:
            if not summary:
                return
            from backend.cli.tui.widgets.scan_line import CompactionCard

            card = CompactionCard(summary=summary)
            self._append_scan_line_card(card)
            return

        if getattr(card, 'state', None) == 'done':
            return

        card.complete(summary=summary)
        card._refresh_line()

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

    def _create_shell_scan_card(
        self,
        command_key: str,
        *,
        command: str | None = None,
        action_id: int | None = None,
    ) -> Any:
        from backend.cli.tui.widgets.scan_line import ShellCard

        self.commit_live_thinking()
        display_command = command if command is not None else command_key
        card = ShellCard(command=display_command)
        card.set_state('running')
        if action_id is not None and action_id >= 0:
            self._register_tool_card(action_id, card, kind='shell')
        else:
            self._pending_shell_cards_by_command[command_key].append(card)
        self._append_scan_line_card(card)
        return card

    def _complete_shell_scan_card(
        self,
        command_key: str,
        *,
        command: str | None = None,
        output: str,
        exit_code: int | None,
        cwd: str | None = None,
        is_background: bool = False,
        action_id: int | None = None,
    ) -> None:
        display_command = command if command is not None else command_key
        card = self._take_tool_card(action_id, expected_kind='shell')
        if card is None and (action_id is None or action_id < 0):
            queue = self._pending_shell_cards_by_command.get(command_key)
            card = queue.popleft() if queue else None
            if queue is not None and not queue:
                self._pending_shell_cards_by_command.pop(command_key, None)

        if card is None:
            from backend.cli.tui.widgets.scan_line import ShellCard

            card = ShellCard(
                command=display_command,
                output=output,
                exit_code=exit_code,
                cwd=cwd or '',
                is_background=is_background,
            )
            self._append_scan_line_card(card)
            return

        card.output = output
        card.exit_code = exit_code
        card.cwd = cwd or card.cwd
        card.is_background = is_background
        if is_background:
            card.set_state('background')
        elif exit_code == 0:
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
        action_id: int | None = None,
        action_kind: str = 'terminal',
    ) -> Any:
        from backend.cli.tui.widgets.scan_line import TerminalCard

        self.commit_live_thinking()
        if not hasattr(self, '_pending_terminal_scan_cards'):
            self._init_terminal_state(self)
        card = TerminalCard(
            session_id=session_id,
            session_label=session_label,
            cwd=cwd,
            command=command,
        )
        card.set_state('running')
        self._pending_terminal_scan_card = card
        if action_id is not None and action_id >= 0:
            self._register_tool_card(action_id, card, kind=action_kind)
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
        state: str | None = None,
    ) -> None:
        if card is None:
            return
        card.session_id = session_id or card.session_id
        card.session_label = session_label or card.session_label
        card.cwd = cwd or card.cwd
        card.command = command or card.command
        card.scrollback = scrollback or card.scrollback
        card.exit_code = exit_code
        if state is not None:
            card.set_state(state)
        elif exit_code == 0:
            card.set_state('done')
        elif exit_code is not None:
            card.set_state('failed')
        else:
            card.set_state('running')
        card._refresh_line()

    def _register_tool_card(self, action_id: int, card: Any, *, kind: str) -> None:
        """Correlate a rendered card with the immutable ledger action id."""
        if action_id < 0:
            return
        self._tool_cards_by_action_id[action_id] = card
        self._tool_kinds_by_action_id[action_id] = kind

    def _take_tool_card(
        self, action_id: int | None, *, expected_kind: str | None = None
    ) -> Any | None:
        if action_id is None or action_id < 0:
            return None
        kind = self._tool_kinds_by_action_id.get(action_id)
        if expected_kind is not None and kind != expected_kind:
            return None
        self._tool_kinds_by_action_id.pop(action_id, None)
        return self._tool_cards_by_action_id.pop(action_id, None)

    def _tool_card_kind(self, action_id: int | None) -> str | None:
        if action_id is None or action_id < 0:
            return None
        return self._tool_kinds_by_action_id.get(action_id)

    def _begin_terminal_close_card(self, action_id: int, session_id: str) -> Any:
        """Reuse the session's card for close instead of appending a duplicate."""
        card = self._pending_terminal_scan_cards.get(session_id)
        if card is None:
            card = getattr(self, '_terminal_cards_by_session', {}).get(session_id)
        if card is None:
            card = self._create_terminal_scan_card(
                session_id=session_id,
                session_label=self._terminal_session_label(session_id) or session_id,
                cwd='',
                command='close',
                action_id=action_id,
                action_kind='terminal_close',
            )
            return card
        card.set_state('running')
        card._refresh_line()
        self._register_tool_card(action_id, card, kind='terminal_close')
        return card

    def _fail_tool_scan_card(self, action_id: int | None, content: str) -> bool:
        """Fail a correlated card in place; return whether one was resolved."""
        kind = self._tool_card_kind(action_id)
        card = self._take_tool_card(action_id, expected_kind=kind)
        if card is None:
            return False
        if hasattr(card, 'output'):
            card.output = content
        if hasattr(card, 'scrollback'):
            existing = str(getattr(card, 'scrollback', '') or '')
            card.scrollback = '\n'.join(part for part in (existing, content) if part)
        for attr in ('result', 'error', 'status_message'):
            if hasattr(card, attr):
                setattr(card, attr, content)
        for pending_attr in (
            '_pending_mcp_card',
            '_pending_delegate_card',
            '_pending_acceptance_criteria_card',
            '_last_browser_action_card',
        ):
            if getattr(self, pending_attr, None) is card:
                setattr(self, pending_attr, None)
        card.set_state('failed')
        card._refresh_line()
        return True

    # ── scrollback buffer ────────────────────────────────────────────

    def _accumulate_terminal_scrollback(self, session_id: str, content: str) -> None:
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
        extracted: str = '',
        action_id: int | None = None,
    ) -> Any:
        from backend.cli.tui.widgets.scan_line import BrowserCard

        self.commit_live_thinking()
        card = BrowserCard(
            domain=domain,
            action=action,
            full_url=full_url,
            extracted=extracted,
        )
        card.set_state('done' if extracted else 'running')
        if action_id is not None and action_id >= 0:
            self._register_tool_card(action_id, card, kind='browser')
        self._append_scan_line_card(card)
        return card
