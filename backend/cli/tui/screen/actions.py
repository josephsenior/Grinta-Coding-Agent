"""ScreenActionsMixin: scroll/copy/suspend/confirmation methods."""

from __future__ import annotations

from typing import Any

from backend.cli.tui.dialogs import ConfirmWidget
from backend.cli.tui.widgets.small import Transcript
from backend.core.autonomy import normalize_autonomy_level


class ScreenActionsMixin:
    """Action methods of GrintaScreen (scroll/copy/suspend/confirmation)."""

    def action_suspend(self) -> None:
        self._agent_running = False
        self.app.exit()

    def action_scroll_up(self) -> None:
        """Scroll transcript up by one page."""
        self._get_display().user_scroll_page_up(animate=False)

    def action_scroll_down(self) -> None:
        """Scroll transcript down by one page."""
        self._get_display().user_scroll_page_down(animate=False)

    def action_scroll_home(self) -> None:
        """Scroll transcript to top."""
        self._get_display().user_scroll_home(animate=False)

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

    def _refresh_scanline_cards(self) -> None:
        """250 ms refresh loop — update live summaries for running scan-line cards."""
        renderer = getattr(self, '_renderer', None)
        if renderer is not None and getattr(renderer, '_async_drain_active', False):
            return
        try:
            display = self._get_display()
        except Exception:
            return
        if getattr(display, '_under_backpressure', False):
            return
        from backend.cli.tui.widgets.scan_line import ScanLineCard
        from backend.cli.tui.widgets.scan_line.cards import (
            advance_running_ellipsis_frame,
        )

        advance_running_ellipsis_frame()
        for card in list(display.query(ScanLineCard)):
            try:
                card.refresh_summary()
            except Exception:
                pass

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
        if ac is not None:
            return normalize_autonomy_level(getattr(ac, 'autonomy_level', '')) == 'full'
        return False

    def _get_pending_action(self) -> Any:
        try:
            action_service = getattr(self._controller, 'action_service', None)
            if action_service is not None:
                return action_service.get_pending_action()
        except Exception:
            pass
        return None

    def _extract_pending_details(self, pending: Any) -> tuple[str, str]:
        target = ''
        risk_raw = 'UNKNOWN'
        if pending is None:
            return target, risk_raw
        if hasattr(pending, 'command') and pending.command:
            target = pending.command
        elif hasattr(pending, 'path') and pending.path:
            target = pending.path
        risk = getattr(pending, 'security_risk', None)
        if risk is not None:
            risk_raw = self._normalize_risk_key(risk)
        return target, risk_raw

    def _build_confirm_options(self) -> list[tuple[str, str]]:
        options: list[tuple[str, str]] = [
            ('approve', 'Accept'),
        ]
        ac = getattr(self._controller, 'autonomy_controller', None)
        if ac is not None and hasattr(ac, 'remember_always_allow'):
            options.append(('always', 'Always'))
        options.append(('reject', 'Reject'))
        return options

    def _apply_confirm_result(
        self,
        result: str,
        pending: Any,
    ) -> None:
        ac = getattr(self._controller, 'autonomy_controller', None)
        if result == 'approve':
            approved = True
        elif result == 'always':
            approved = True
            if ac is not None and pending is not None:
                ac.remember_always_allow(pending)
        else:
            approved = False
        return self._controller.apply_user_decision(approved=approved)

    async def _handle_confirmation_dialog(self) -> None:
        """Show inline confirmation widget and wait for user decision."""
        pending = self._get_pending_action()

        if self._is_full_autonomy():
            await self._controller.apply_user_decision(approved=True)
            return

        action_type_raw = type(pending).__name__ if pending else 'Unknown'
        action_type = self._ACTION_TYPE_LABELS.get(action_type_raw, action_type_raw)
        target, risk_raw = self._extract_pending_details(pending)
        risk_label, risk_class = self._RISK_LABELS.get(risk_raw, ('Unknown', 'dim'))

        options = self._build_confirm_options()

        widget = self.query_one('#confirm-widget', ConfirmWidget)
        widget.configure(
            action_type, risk_label, risk_class, target, options, recommended=0
        )
        widget.show()
        try:
            result = await widget.wait_for_decision()
        finally:
            widget.hide()

        await self._apply_confirm_result(result, pending)
