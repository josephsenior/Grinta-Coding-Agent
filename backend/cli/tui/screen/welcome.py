from __future__ import annotations

from textual.events import ScreenResume
from textual.widgets import (
    Select,
    TextArea,
)

from backend.cli.tui.widgets.welcome import (
    WelcomeWidget,
)


class ScreenWelcomeMixin:
    """Welcome-related methods of GrintaScreen."""

    def _get_welcome_widget(self) -> WelcomeWidget | None:
        try:
            display = self._get_display()
        except Exception:
            return None
        for child in display.children:
            if type(child) is WelcomeWidget:
                return child
        return None

    def on_screen_resume(self, _event: ScreenResume) -> None:
        """Restore welcome after modal dialogs when the transcript is still empty."""
        self._show_welcome()

    def _show_welcome(self) -> None:
        if self._is_unmounted:
            return
        try:
            if self._transcript_has_real_content():
                self._hide_welcome()
                return
            if self._get_welcome_widget() is not None:
                self._welcome_visible = True
                return
            display = self._get_display()
            display.mount(WelcomeWidget())
            self._welcome_visible = True
        except Exception:
            pass

    def _hide_welcome(self) -> None:
        if not self._welcome_visible:
            return
        try:
            widget = self._get_welcome_widget()
            if widget is not None:
                widget.remove()
            self._welcome_visible = False
        except Exception:
            self._welcome_visible = False

    def action_welcome_select(self) -> None:
        if not self._welcome_visible:
            return
        ta = self.query_one('#input', TextArea)
        if ta.text.strip():
            return
        widget = self._get_welcome_widget()
        if widget is None:
            return
        text = widget.select_current()
        if text:
            ta.text = text
            self._hide_welcome()
            self.action_submit_input()

    def _handle_welcome_click(self, text: str) -> None:
        if not self._welcome_visible:
            return
        ta = self.query_one('#input', TextArea)
        ta.text = text
        self._hide_welcome()
        self.action_submit_input()

    def on_select_changed(self, event: Select.Changed) -> None:
        event.stop()
        widget_id = event.select.id
        if widget_id in {'hud-autonomy', 'hud-reasoning'} and not getattr(
            self, '_hud_controls_ready', False
        ):
            return
        if widget_id == 'hud-autonomy':
            if self._consume_hud_select_sync_event(widget_id, event.value):
                return
            if getattr(self, '_hud_autonomy_syncing', False):
                return
            self._apply_autonomy_level(event.value)
        elif widget_id == 'hud-reasoning':
            if self._consume_hud_select_sync_event(widget_id, event.value):
                return
            if getattr(self, '_hud_reasoning_syncing', False):
                return
            self._apply_hud_reasoning_effort(str(event.value))
