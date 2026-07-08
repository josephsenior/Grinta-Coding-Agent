"""TUI helpers for interactive prompt cards (``ask_user`` and related flows).

Renders option lists via :class:`~backend.cli.tui.widgets.welcome.CommunicatePromptWidget`
and routes keyboard selection back into the input bar.
"""

from __future__ import annotations

import shlex
from typing import Any

from textual.widget import Widget
from textual.widgets import (
    Label,
    ListItem,
    ListView,
    TextArea,
)

from backend.cli.tui.helpers import (
    _strip_ansi,
    _strip_terminal_control_literals,
)


class ScreenCommunicateMixin:
    """Communicate-card navigation helpers for GrintaScreen."""

    def _find_focusable_cards(self) -> list[Widget]:
        """Return all focusable scan-line cards in the transcript in DOM order."""
        display = self._get_display()
        return [
            c
            for c in display.query('ScanLineCard')
            if c.display and getattr(c, 'can_focus', False)
        ]

    def _set_active_communicate_card(self, card: Any | None) -> None:
        previous = self._active_communicate_card
        if previous is not None and previous is not card:
            try:
                previous.set_active(False)
            except Exception:
                pass
        self._active_communicate_card = card
        if card is not None:
            try:
                card.set_active(True)
            except Exception:
                pass

    def _handle_communicate_navigation(self, key: str) -> bool:
        card = self._active_communicate_card
        if card is None or not getattr(card, 'has_options', False):
            return False
        if key == 'up':
            card.highlight_prev()
            return True
        if key == 'down':
            card.highlight_next()
            return True
        return False

    def _handle_communicate_selection(
        self,
        text: str,
        *,
        card: Any | None = None,
    ) -> None:
        active = card or self._active_communicate_card
        scaffold = ''
        if active is not None:
            try:
                header = str(getattr(active, 'header', '') or '')
            except Exception:
                header = ''
            if header:
                scaffold = (
                    f'[user answered the prompt: "{header}" \u2014 chose: "{text}"]'
                )
            try:
                active.set_active(False)
            except Exception:
                pass
            if active is self._active_communicate_card:
                self._active_communicate_card = None
        ta = self.query_one('#input', TextArea)
        ta.text = f'{scaffold} {text}'.strip() if scaffold else text
        self.action_submit_input()

    def action_focus_next_card(self) -> None:
        """Focus the next transcript card (jumps in from the input on first press)."""
        if self._welcome_visible:
            ta = self.query_one('#input', TextArea)
            if not ta.text.strip():
                widget = self._get_welcome_widget()
                if widget is not None:
                    widget.highlight_next()
                return
        cards = self._find_focusable_cards()
        if not cards:
            return
        focused = self.screen.focused
        if focused in cards:
            start = (cards.index(focused) + 1) % len(cards)
        else:
            start = 0
        cards[start].focus()

    def action_focus_prev_card(self) -> None:
        """Focus the previous transcript card (jumps in from the input on first press)."""
        if self._welcome_visible:
            ta = self.query_one('#input', TextArea)
            if not ta.text.strip():
                widget = self._get_welcome_widget()
                if widget is not None:
                    widget.highlight_prev()
                return
        cards = self._find_focusable_cards()
        if not cards:
            return
        focused = self.screen.focused
        if focused in cards:
            start = cards.index(focused) - 1
        else:
            start = -1
        cards[start].focus()

    def _update_suggestions_list(self, text: str) -> None:
        try:
            lst = self.query_one('#suggestions-list', ListView)
        except Exception:
            return
        stripped = _strip_ansi(text).strip()
        if not stripped.startswith('/'):
            lst.add_class('-hidden')
            self._suggestion_matches = []
            return
        try:
            parts = shlex.split(stripped)
        except ValueError:
            lst.add_class('-hidden')
            self._suggestion_matches = []
            return
        if not parts:
            lst.add_class('-hidden')
            self._suggestion_matches = []
            return
        cmd = parts[0].lower()
        matches = [name for name in self._SLASH_HINTS if name.startswith(cmd)]
        if not matches:
            lst.add_class('-hidden')
            self._suggestion_matches = []
            return
        self._suggestion_matches = matches
        lst.clear()
        from backend.cli.tui.widgets.command_list import (
            CommandListRow,
            slash_command_detail,
        )

        for name in matches:
            hint = slash_command_detail(name, self._SLASH_HINTS[name])
            lst.append(ListItem(CommandListRow(name, hint)))
        lst.index = 0
        lst.remove_class('-hidden')

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == 'input':
            text = _strip_terminal_control_literals(event.text_area.text)
            if text != event.text_area.text:
                event.text_area.text = text
                return
            self._update_suggestions_list(text)
            self._update_command_hint(text)
            refresh = getattr(self, '_refresh_input_attachment_hint', None)
            if callable(refresh):
                refresh()
            else:
                try:
                    hint = self.query_one('#input-hint', Label)
                    hint.display = not bool(text.strip())
                except Exception:
                    pass
            self._resize_input_bar()
