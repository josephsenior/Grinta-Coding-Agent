"""Small widget classes extracted from backend.cli.tui.app.

Pure code motion: class bodies are byte-identical to the
pre-split version. Kept in a single module because each class
is <3 KB and they share similar import profiles.
"""

from __future__ import annotations

from typing import Any

import pyperclip
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Label, Select, Static, TextArea

from backend.core.interaction_modes import AGENT_MODE, VISIBLE_INTERACTION_MODES


class InfoSidebar(VerticalScroll):
    """Sidebar for Mission Control info (Tasks, MCPs, Skills)."""

    def update(self, *args: Any, **kwargs: Any) -> None:
        """No-op update for backward compatibility and test mock compatibility."""
        pass


class Transcript(VerticalScroll):
    """Scrollable conversation transcript container with auto-scroll awareness."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._user_scrolled_away = False

    def compose(self) -> ComposeResult:
        yield Static(id='scroll-badge', classes='-hidden')

    def on_mount(self) -> None:
        self._scroll_badge = self.query_one('#scroll-badge', Static)

    def _was_at_bottom(self, threshold: int = 3) -> bool:
        return self.max_scroll_y - self.scroll_y <= threshold

    def on_scroll(self, _event: Widget.Scroll) -> None:
        if not self._scroll_badge:
            return
        if self._was_at_bottom():
            if self._user_scrolled_away:
                self._user_scrolled_away = False
                self._scroll_badge.add_class('-hidden')
        else:
            if not self._user_scrolled_away:
                self._user_scrolled_away = True
                self._scroll_badge.remove_class('-hidden')

    def append_widget(self, widget: Static | Container) -> None:
        """Mount a widget and auto-scroll unless user scrolled up."""
        widget.styles.offset = (0, -1)
        self.mount(widget)
        try:
            widget.animate('offset', (0, 0), duration=0.2)
        except Exception:
            widget.styles.offset = (0, 0)
        if not self._user_scrolled_away:
            self.scroll_end(animate=False)

    def write(self, renderable: Any) -> None:
        """Compatibility method for RichLog interface."""
        self.append_widget(Static(renderable))

    def force_scroll_end(self) -> None:
        """Scroll to bottom regardless of user scroll state."""
        self._user_scrolled_away = False
        self._scroll_badge.add_class('-hidden')
        self.scroll_end(animate=False)

    def clear(self) -> None:
        """Compatibility method for RichLog interface."""
        self.remove_children()
        self._user_scrolled_away = False
        self.mount(Static('', id='scroll-badge', classes='-hidden'))
        self._scroll_badge = self.query_one('#scroll-badge', Static)


class InputBar(Horizontal):
    """Bottom input row with border and prompt."""


class PromptTextArea(TextArea):
    """Input area that routes arrow navigation to welcome suggestions when idle."""

    def _on_paste(self, event: events.Paste) -> None:
        """Handle paste events by reading the system clipboard directly.

        In most terminals (Windows Terminal, etc.), Ctrl+V is intercepted and
        forwarded as a bracketed paste event. For large clipboard content, the
        terminal/PTY can silently truncate the data mid-stream — the paste event
        arrives with incomplete or empty text, so the user sees nothing.

        Bypass this by reading the system clipboard directly via pyperclip.
        Falls back to the paste-event text when pyperclip is unavailable.
        """
        if self.read_only:
            return
        try:
            clipboard = pyperclip.paste()
        except Exception:
            clipboard = event.text
        event.prevent_default()
        if result := self._replace_via_keyboard(clipboard, *self.selection):
            self.move_cursor(result.end_location)

    def action_paste(self) -> None:
        """Paste from system clipboard directly.

        This handles the case where Ctrl+V is NOT intercepted by the terminal
        and reaches the app as a key binding.
        """
        if self.read_only:
            return
        try:
            clipboard = pyperclip.paste()
        except Exception:
            return super().action_paste()
        if result := self._replace_via_keyboard(clipboard, *self.selection):
            self.move_cursor(result.end_location)

    def on_key(self, event: events.Key) -> None:
        screen = getattr(self, 'screen', None)
        if event.key in {'up', 'down'} and bool(screen) and not self.text.strip():
            if getattr(screen, '_welcome_visible', False):
                if event.key == 'up' and hasattr(screen, 'action_focus_prev_card'):
                    screen.action_focus_prev_card()
                elif event.key == 'down' and hasattr(screen, 'action_focus_next_card'):
                    screen.action_focus_next_card()
                event.prevent_default()
                event.stop()
                return
            if hasattr(
                screen, '_handle_communicate_navigation'
            ) and screen._handle_communicate_navigation(event.key):
                event.prevent_default()
                event.stop()
                return


class HUD(Vertical):
    """Multi-line status bar at the very bottom."""

    def compose(self) -> ComposeResult:
        with Horizontal(id='hud-line-2-row'):
            yield Label('[#7a6a4a]Mode:[/]', id='hud-label-mode')
            yield Select(
                [(c.capitalize(), c) for c in VISIBLE_INTERACTION_MODES],
                value=AGENT_MODE,
                id='hud-mode',
                allow_blank=False,
            )
            yield Label('[#6a7a9a]Autonomy:[/]', id='hud-label-autonomy')
            yield Select(
                [(c.capitalize(), c) for c in ('conservative', 'balanced', 'full')],
                value='balanced',
                id='hud-autonomy',
                allow_blank=False,
            )
            yield Label(id='hud-line-2')
        yield Label(id='hud-line-1')


class RendererDrainRequested(Message):
    """Message requesting the screen to drain queued renderer events."""
