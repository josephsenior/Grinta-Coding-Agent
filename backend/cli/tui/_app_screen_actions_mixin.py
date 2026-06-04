"""_AppScreenActionsMixin: scroll/copy/suspend/confirmation methods."""

from __future__ import annotations

from typing import Any

from backend.cli.tui._app_dialogs import ConfirmWidget
from backend.cli.tui._app_small_widgets import Transcript
from backend.core.enums import AgentState, EventSource
from backend.ledger.action import ChangeAgentStateAction
from backend.orchestration.autonomy import normalize_autonomy_level


class _AppScreenActionsMixin:
    """Action methods of GrintaScreen (scroll/copy/suspend/confirmation)."""

    def action_suspend(self) -> None:
        self._agent_running = False
        self.app.exit()

    def action_scroll_up(self) -> None:
        """Scroll transcript up by one page."""
        self._get_display().user_scroll_page_up(animate=True)

    def action_scroll_down(self) -> None:
        """Scroll transcript down by one page."""
        self._get_display().user_scroll_page_down(animate=True)

    def action_scroll_home(self) -> None:
        """Scroll transcript to top."""
        self._get_display().user_scroll_home(animate=True)

    def action_scroll_end(self) -> None:
        """Scroll transcript to bottom."""
        self._scroll_to_bottom()

    def action_toggle_sidebar(self) -> None:
        """Toggle sidebar visibility."""
        sidebar = self.query_one('#sidebar')
        if sidebar.has_class('-hidden'):
            sidebar.remove_class('-hidden')
            transcript = self.query_one('#main-display', Transcript)
            transcript.styles.width = '70%'
        else:
            sidebar.add_class('-hidden')
            transcript = self.query_one('#main-display', Transcript)
            transcript.styles.width = '100%'

    def action_show_help(self) -> None:
        """Show help information."""
        self.show_help()

    def _scroll_to_bottom(self) -> None:
        self._get_display().user_scroll_end()

    @staticmethod
    def _normalize_risk_key(risk: Any) -> str:
        """Return the display key used by the confirmation risk map."""
        if risk is None:
            return 'UNKNOWN'

        name = getattr(risk, 'name', None)
        if isinstance(name, str) and name:
            return name.upper()

        value = getattr(risk, 'value', risk)
        if isinstance(value, int):
            return {
                -1: 'UNKNOWN',
                0: 'LOW',
                1: 'MEDIUM',
                2: 'HIGH',
            }.get(value, 'UNKNOWN')

        risk_text = str(value).strip().upper()
        try:
            return {
                -1: 'UNKNOWN',
                0: 'LOW',
                1: 'MEDIUM',
                2: 'HIGH',
            }[int(risk_text)]
        except (KeyError, TypeError, ValueError):
            pass

        if '.' in risk_text:
            risk_text = risk_text.rsplit('.', 1)[-1]
        from backend.cli.tui.app import GrintaScreen

        if risk_text in GrintaScreen._RISK_LABELS:
            return risk_text
        return 'UNKNOWN'

    def _is_full_autonomy(self) -> bool:
        controller = getattr(self, '_controller', None)
        ac = getattr(controller, 'autonomy_controller', None)
        raw_level = getattr(ac, 'autonomy_level', '') if ac is not None else ''
        return normalize_autonomy_level(raw_level) == 'full'

    async def _handle_confirmation_dialog(self) -> None:
        """Show inline confirmation widget and wait for user decision."""
        pending = None
        try:
            action_service = getattr(self._controller, 'action_service', None)
            if action_service is not None:
                pending = action_service.get_pending_action()
        except Exception:
            pass

        if self._is_full_autonomy():
            self._event_stream.add_event(
                ChangeAgentStateAction(agent_state=AgentState.USER_CONFIRMED),
                EventSource.USER,
            )
            return

        action_type_raw = type(pending).__name__ if pending else 'Unknown'
        action_type = self._ACTION_TYPE_LABELS.get(action_type_raw, action_type_raw)
        target = ''
        risk_raw = 'UNKNOWN'

        if pending:
            if hasattr(pending, 'command') and pending.command:
                target = pending.command
            elif hasattr(pending, 'path') and pending.path:
                target = pending.path

            risk = getattr(pending, 'security_risk', None)
            if risk is not None:
                risk_raw = self._normalize_risk_key(risk)

        risk_label, risk_class = self._RISK_LABELS.get(risk_raw, ('Unknown', 'dim'))

        options: list[tuple[str, str]] = [
            ('approve', 'Accept'),
        ]

        ac = getattr(self._controller, 'autonomy_controller', None)
        if ac is not None and hasattr(ac, 'remember_always_allow'):
            options.append(('always', 'Always'))
        options.append(('reject', 'Reject'))

        widget = self.query_one('#confirm-widget', ConfirmWidget)
        widget.configure(
            action_type, risk_label, risk_class, target, options, recommended=0
        )
        widget.show()
        try:
            result = await widget.wait_for_decision()
        finally:
            widget.hide()

        if result == 'approve':
            decision = AgentState.USER_CONFIRMED
        elif result == 'always':
            decision = AgentState.USER_CONFIRMED
            if ac is not None and pending is not None:
                ac.remember_always_allow(pending)
        else:
            decision = AgentState.USER_REJECTED

        action = ChangeAgentStateAction(agent_state=decision)
        self._event_stream.add_event(action, EventSource.USER)
