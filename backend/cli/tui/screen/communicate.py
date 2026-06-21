"""TUI surface for ``communicate_with_user`` structured actions.

Renders interactive cards (clarification, proposal, confirm, inform, escalate)
via :class:`~backend.cli.tui.widgets.welcome.CommunicatePromptWidget`.

Newer flows may use ``ask_user`` elsewhere in the screen stack; this module
remains the handler for legacy communicate action types and is covered by
``backend/tests/unit/cli/tui/test_communicate.py``.
"""

from __future__ import annotations

import shlex
from typing import Any, Mapping

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
from backend.cli.tui.widgets.welcome import (
    CommunicatePromptWidget,
)
from backend.ledger.action import (
    ClarificationRequestAction,
    ConfirmRequestAction,
    EscalateToHumanAction,
    InformAction,
    ProposalAction,
    UncertaintyAction,
)


def _stringify_attempt(attempt: object) -> str:
    """Render a single attempt entry as a displayable line."""
    if isinstance(attempt, Mapping):
        action = str(attempt.get('action', '') or '').strip()
        result = str(attempt.get('result', '') or '').strip()
        if action and result:
            return f'{action} \u2192 {result}'
        return action or str(attempt)
    return str(attempt)


class ScreenCommunicateMixin:
    """Communicate-related methods of GrintaScreen."""

    def add_communicate_clarification(self, action: ClarificationRequestAction) -> None:
        """Agent asks a question — render an interactive communicate card."""
        options = self._materialize_options(action.options)
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
        """Agent expresses uncertainty. Non-blocking — informational."""
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
        # Uncertainty is informational, not a gate; do not block the input.

    def add_communicate_proposal(self, action: ProposalAction) -> None:
        """Agent proposes a plan.

        The recommended option is marked with a ``(recommended)`` suffix in
        its label; the user navigates to it and presses Enter to accept.
        We deliberately do NOT pre-highlight it: visual cues are enough and
        pre-selection would require racing the widget's mount order.
        """
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

    def add_communicate_confirm(self, action: ConfirmRequestAction) -> None:
        """Agent requires explicit user OK before a risky step.

        Always blocking. Two options expected: positive then negative. The
        default is the deny option (index 1) so a misclick or timeout
        rejects — safety first.
        """
        options = self._materialize_options(action.options)
        if not options:
            options = [
                ('Yes, do it', 'Yes, do it', '', False),
                ('No, abort', 'No, abort', '', False),
            ]
        details: list[str] = []
        if action.context:
            details.append(action.context)
        if action.default_index == 0:
            details.append('Auto-confirms if you do not respond in time.')
        else:
            details.append('Auto-denies if you do not respond in time (safe default).')
        default_index = (
            1
            if not (0 <= action.default_index < len(options))
            else action.default_index
        )
        card = CommunicatePromptWidget(
            'Confirm',
            action.question or 'The agent wants to perform a risky action.',
            context=action.thought,
            details=details,
            options=options,
            preselected_index=default_index,
        )
        self._write_log(card)
        self._set_active_communicate_card(card)

    def add_communicate_inform(self, action: InformAction) -> None:
        """Non-blocking status update from the agent."""
        details = [action.context] if action.context else []
        card = CommunicatePromptWidget(
            'Status',
            action.text or 'Status update.',
            context=action.thought,
            details=details,
        )
        self._write_log(card)
        # Inform never blocks; the turn continues.

    def add_communicate_escalate(self, action: EscalateToHumanAction) -> None:
        """Agent escalates to human after repeated failures."""
        details = [_stringify_attempt(a) for a in (action.attempts_made or [])]
        if action.specific_help_needed:
            details.append(f'Help needed: {action.specific_help_needed}')
        card = CommunicatePromptWidget(
            'Need Your Input',
            action.reason or 'The agent needs your input to continue.',
            context=action.thought,
            details=details,
        )
        self._write_log(card)
        # Escalation is informational unless the agent also supplied a
        # specific question via specific_help_needed. If so, the human
        # should be able to reply with a free-form answer, but we don't
        # block the orchestrator here — same as uncertainty.

    @staticmethod
    def _materialize_options(
        raw: list[object] | tuple[object, ...] | None,
    ) -> list[tuple[str, str, str, bool]]:
        """Convert a list of str or {label, description} dicts to widget rows."""
        out: list[tuple[str, str, str, bool]] = []
        for opt in raw or []:
            if isinstance(opt, Mapping):
                label = str(opt.get('label', '') or '').strip()
                if not label:
                    continue
                description = str(opt.get('description', '') or '').strip()
                out.append((label, label, description, False))
            elif opt:
                out.append((str(opt), str(opt), '', False))
        return out

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
