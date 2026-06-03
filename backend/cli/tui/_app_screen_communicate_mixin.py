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

from backend.cli.tui._app_helpers import (
    _strip_ansi,
    _strip_terminal_control_literals,
)
from backend.cli.tui._app_welcome_widgets import (
    CommunicatePromptWidget,
)
from backend.ledger.action import (
    ClarificationRequestAction,
    EscalateToHumanAction,
    ProposalAction,
    UncertaintyAction,
)


class _AppScreenCommunicateMixin:
    """Communicate-related methods of GrintaScreen."""

    def add_communicate_clarification(self, action: ClarificationRequestAction) -> None:
        """Agent asks a question — render an interactive communicate card."""
        options = [(opt, opt, '', False) for opt in (action.options or [])]
        details = [action.context] if action.context else []
        card = CommunicatePromptWidget(
            'Question',
            action.question or 'The agent needs your input.',
            context=action.thought,
            details=details,
            options=options,
        )
        self._write_log(card)
        self._set_active_communicate_card(card if options else None)

    def add_communicate_uncertainty(self, action: UncertaintyAction) -> None:
        """Agent expresses uncertainty."""
        details = list((action.specific_concerns or [])[:5])
        if action.requested_information:
            details.append(f'Needed: {action.requested_information}')
        card = CommunicatePromptWidget(
            'Needs Context',
            'The agent needs more context before it can continue confidently.',
            context=action.thought,
            details=details,
        )
        self._write_log(card)
        self._set_active_communicate_card(None)

    def add_communicate_proposal(self, action: ProposalAction) -> None:
        """Agent proposes a plan."""
        options: list[tuple[str, str, str, bool]] = []
        for i, opt in enumerate(action.options or []):
            label = opt.get(
                'name',
                opt.get('title', opt.get('approach', f'Option {i + 1}')),
            )
            description = opt.get('description', '')
            if not description:
                pros = ', '.join(opt.get('pros') or [])
                cons = ', '.join(opt.get('cons') or [])
                fragments = []
                if pros:
                    fragments.append(f'Pros: {pros}')
                if cons:
                    fragments.append(f'Cons: {cons}')
                description = ' | '.join(fragments)
            options.append((label, label, description, i == action.recommended))

        card = CommunicatePromptWidget(
            'Options',
            'Choose a path for the agent to take.',
            context=action.thought,
            details=[action.rationale] if action.rationale else [],
            options=options,
        )
        self._write_log(card)
        self._set_active_communicate_card(card if options else None)

    def add_communicate_escalate(self, action: EscalateToHumanAction) -> None:
        """Agent escalates to human."""
        details = list(action.attempts_made or [])
        if action.specific_help_needed:
            details.append(f'Help needed: {action.specific_help_needed}')
        card = CommunicatePromptWidget(
            'Need Your Input',
            action.reason or 'The agent needs your input to continue.',
            context=action.thought,
            details=details,
        )
        self._write_log(card)
        self._set_active_communicate_card(None)

    def _find_focusable_cards(self) -> list[Widget]:
        """Return all ActivityCard widgets in the transcript in DOM order."""
        from backend.cli.tui.widgets.activity_card import ActivityCard

        display = self._get_display()
        return [c for c in display.query(ActivityCard) if c.display]

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
        if active is not None:
            try:
                active.set_active(False)
            except Exception:
                pass
            if active is self._active_communicate_card:
                self._active_communicate_card = None
        ta = self.query_one('#input', TextArea)
        ta.text = text
        self.action_submit_input()

    def action_focus_next_card(self) -> None:
        """Move keyboard focus to the next ActivityCard or suggestion."""
        if self._welcome_visible:
            ta = self.query_one('#input', TextArea)
            if not ta.text.strip():
                widget = self._get_welcome_widget()
                if widget is not None:
                    widget.highlight_next()
                return
        if self.focused and self.focused is self.query_one('#input', TextArea):
            return
        cards = self._find_focusable_cards()
        if not cards:
            return
        focused = self.screen.focused
        start = 0
        if focused in cards:
            start = (cards.index(focused) + 1) % len(cards)
        cards[start].focus()

    def action_focus_prev_card(self) -> None:
        """Move keyboard focus to the previous ActivityCard or suggestion."""
        if self._welcome_visible:
            ta = self.query_one('#input', TextArea)
            if not ta.text.strip():
                widget = self._get_welcome_widget()
                if widget is not None:
                    widget.highlight_prev()
                return
        if self.focused and self.focused is self.query_one('#input', TextArea):
            return
        cards = self._find_focusable_cards()
        if not cards:
            return
        focused = self.screen.focused
        start = -1
        if focused in cards:
            start = cards.index(focused) - 1
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
        for name in matches:
            hint = self._SLASH_HINTS[name]
            lst.append(ListItem(Label(f'[#eacb8a]{name}[/]  [#54597b]{hint}[/]')))
        lst.index = 0
        lst.remove_class('-hidden')

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == 'input':
            text = _strip_terminal_control_literals(event.text_area.text)
            if text != event.text_area.text:
                event.text_area.text = text
                return
            self._update_suggestions_list(text)
            try:
                hint = self.query_one('#input-hint', Label)
                hint.display = not bool(text.strip())
            except Exception:
                pass
            self._resize_input_bar()
