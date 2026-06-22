"""WelcomeWidget and CommunicatePromptWidget extracted from app.py.

Pure code motion: class bodies are byte-identical to the
pre-split version. WelcomeWidget is a Vertical container with
starter task suggestions. CommunicatePromptWidget is a
subclass that adds interactive card selection.
"""

from __future__ import annotations

from typing import Any

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from backend.cli.tui.constants import (
    _WELCOME_SUGGESTION_DETAILS,
    _WELCOME_SUGGESTIONS,
)
from backend.cli.tui.helpers import _get_welcome_figlet


class WelcomeWidget(Vertical):
    """Empty-state welcome panel with interactive task suggestions."""

    def __init__(
        self,
        *,
        header: str = 'Start with this workspace.',
        subheader: str = 'Pick a starter task or type your own request below.',
        suggestions: list[str] | None = None,
        suggestion_details: list[str] | None = None,
        callback_name: str = '_handle_welcome_click',
        show_logo: bool = True,
    ) -> None:
        super().__init__()
        self._header_text = header
        self._subheader_text = subheader
        self._suggestions = (
            list(suggestions) if suggestions is not None else list(_WELCOME_SUGGESTIONS)
        )
        self._suggestion_details = list(
            suggestion_details
            if suggestion_details is not None
            else _WELCOME_SUGGESTION_DETAILS
        )
        if len(self._suggestion_details) < len(self._suggestions):
            self._suggestion_details.extend(
                [''] * (len(self._suggestions) - len(self._suggestion_details))
            )
        self._callback_name = callback_name
        self._show_logo = show_logo
        self._selected = 0
        self._items: list[Static] = []

    def compose(self) -> ComposeResult:
        if self._show_logo:
            yield Static('', id='welcome-logo')
            yield Horizontal(
                Static(
                    'Local-First Autonomous Software Engineer.',
                    id='slogan-text',
                ),
                Static('Pure Grit.', id='slogan-tagline'),
                id='welcome-slogan-row',
            )
            yield Static(
                '[#c8d4e8]Start with a concrete task, or choose a guided starter.[/]',
                id='welcome-slogan',
            )
            yield Static(
                '[#6f83aa]Current workspace context, tools, and session state are already wired in.[/]',
                id='welcome-tagline',
            )
            yield Static(
                '[#8f9fc1]Use up/down + Enter, or click a starter task. Press F1 or /help for commands. New here? Run /health or grinta doctor.[/]',
                id='welcome-instruction',
            )
        else:
            yield Static(self._header_text, id='welcome-header')
            yield Static(self._subheader_text, id='welcome-subheader')
        for _text in self._suggestions:
            yield Static('', classes='welcome-item')

    def on_mount(self) -> None:
        if self._show_logo:
            width = self.screen.size.width
            logo_static = self.query_one('#welcome-logo', Static)
            if width >= 80:
                logo_static.update(_get_welcome_figlet())
            else:
                logo_static.update('[#6F86B6]GRINTA[/]')
        # Preserve any selection set before mount (e.g. by a pre-selection
        # call on the active communicate card). Default to 0 otherwise.
        self._selected = getattr(self, '_selected', 0)
        self._items = list(self.query('.welcome-item'))
        self._cascade_timers: list[Any] = []
        for item in self._items:
            item.display = False
        self._cascade(self._selected)

    def _cascade(self, idx: int) -> None:
        if idx >= len(self._items):
            self._highlight(self._selected)
            return
        self._items[idx].display = True
        timer = self.set_timer(0.15, lambda i=idx: self._cascade(i + 1))
        self._cascade_timers.append(timer)

    def on_unmount(self) -> None:
        for timer in self._cascade_timers:
            try:
                timer.stop()
            except Exception:
                pass
        self._cascade_timers.clear()

    @property
    def header(self) -> str:
        """Public accessor for the header text.

        Used by callers that want to reference the card's question/title
        in a reply, e.g. to scaffold a user reply that preserves question context.
        """
        return self._header_text

    def _highlight(self, idx: int) -> None:
        for i, item in enumerate(self._items):
            item.update(self._render_suggestion(i, selected=i == idx))
        self._selected = idx

    def _render_suggestion(self, index: int, *, selected: bool) -> str:
        icon = '>' if selected else '-'
        label_style = '#5eead4' if selected else '#8ea2c8'
        detail = (self._suggestion_details[index] or '').strip()
        text = f'  {icon} [{label_style}]{self._suggestions[index]}[/]'
        if detail:
            text += f'\n    [#6b7280]{detail}[/]'
        return text

    def highlight_prev(self) -> None:
        if self._selected > 0:
            self._highlight(self._selected - 1)

    def highlight_next(self) -> None:
        if self._selected < len(self._suggestions) - 1:
            self._highlight(self._selected + 1)

    def select_current(self) -> str | None:
        if 0 <= self._selected < len(self._suggestions):
            return self._suggestions[self._selected]
        return None

    def on_click(self, event: events.Click) -> None:
        target = event.widget
        if target is None:
            return
        for i, item in enumerate(self._items):
            if target is item:
                self._highlight(i)
                text = self.select_current()
                if text:
                    event.prevent_default()
                    event.stop()
                    screen = getattr(self, 'screen', None)
                    if screen and hasattr(screen, self._callback_name):
                        getattr(screen, self._callback_name)(text)
                break


class CommunicatePromptWidget(WelcomeWidget):
    """Interactive transcript prompt for ask_user."""

    def __init__(
        self,
        title: str,
        prompt: str,
        *,
        context: str = '',
        details: list[str] | None = None,
        options: list[tuple[str, str, str, bool]] | None = None,
        preselected_index: int = 0,
    ) -> None:
        details_text = ' '.join(details or [])
        helper = 'Use up/down + Enter, or click an option.'
        parts = [part for part in (context, details_text, helper) if part]
        super().__init__(
            header=f'{title}: {prompt}',
            subheader=' '.join(parts) if parts else helper,
            suggestions=[
                option[0] + (' (recommended)' if option[3] else '')
                for option in (options or [])
            ],
            suggestion_details=[option[2] for option in (options or [])],
            callback_name='_handle_communicate_selection',
            show_logo=False,
        )
        self._values = [option[1] for option in (options or [])]
        self._active = bool(self._values)
        self._submitted: int | None = None
        # Clamp to valid range; -1 means "leave default".
        n = len(self._values)
        if 0 <= preselected_index < n:
            self._selected = preselected_index

    def on_mount(self) -> None:
        # Preserve any selection set before mount (e.g. by a pre-selection
        # call on the active communicate card). Default to 0 otherwise.
        self._selected = getattr(self, '_selected', 0)
        self._items = list(self.query('.welcome-item'))
        self._cascade_timers = []
        for item in self._items:
            item.display = True
        if self._items:
            self._highlight(self._selected)

    @property
    def has_options(self) -> bool:
        return bool(self._values)

    @property
    def current_value(self) -> str | None:
        if not self._values:
            return None
        return self._values[self._selected]

    def set_active(self, active: bool) -> None:
        self._active = active and self.has_options

    def mark_submitted(self, index: int | None = None) -> None:
        if not self._values:
            return
        self._submitted = self._selected if index is None else index
        self._active = False

    def action_submit_option(self) -> None:
        if not self._active or not self._values:
            return
        self.mark_submitted(self._selected)
        screen = getattr(self, 'screen', None)
        if screen and hasattr(screen, '_handle_communicate_selection'):
            screen._handle_communicate_selection(
                self._values[self._selected], card=self
            )

    def on_click(self, event: events.Click) -> None:
        target = event.widget
        if target is None:
            return
        for i, item in enumerate(self._items):
            if target is item:
                self._highlight(i)
                self.action_submit_option()
                event.prevent_default()
                event.stop()
                return
