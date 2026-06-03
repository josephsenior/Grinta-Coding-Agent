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
from textual.containers import Horizontal, Vertical, VerticalScroll
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
        self._scroll_badge: Static | None = None

    def compose(self) -> ComposeResult:
        yield Static(id='scroll-badge', classes='-hidden')

    def on_mount(self) -> None:
        self._scroll_badge = self.query_one('#scroll-badge', Static)

    def _was_at_bottom(self, threshold: float = 0.5) -> bool:
        if self.max_scroll_y <= 0:
            return True
        current_distance = self.max_scroll_y - self.scroll_y
        target_distance = self.max_scroll_y - self.scroll_target_y
        return current_distance <= threshold or target_distance <= threshold

    def _set_user_scrolled_away(self, value: bool) -> None:
        self._user_scrolled_away = value
        badge = self._scroll_badge
        if badge is None:
            return
        if value:
            badge.remove_class('-hidden')
        else:
            badge.add_class('-hidden')

    def _sync_scroll_state_from_position(self) -> None:
        self._set_user_scrolled_away(not self._was_at_bottom())

    def should_follow_tail(self) -> bool:
        """Return True when live updates should keep the transcript pinned."""
        if self._user_scrolled_away:
            return False
        if self._was_at_bottom():
            return True
        self._set_user_scrolled_away(True)
        return False

    def pause_auto_scroll(self) -> None:
        """Stop live updates from pulling the transcript back to the bottom."""
        if self.max_scroll_y > 0:
            self._set_user_scrolled_away(True)

    def on_scroll(self, _event: Widget.Scroll) -> None:
        self._sync_scroll_state_from_position()

    def _on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        self.pause_auto_scroll()
        super()._on_mouse_scroll_up(event)

    def _on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        super()._on_mouse_scroll_down(event)
        self.call_after_refresh(self._sync_scroll_state_from_position)

    def user_scroll_page_up(self, *, animate: bool = True) -> None:
        self.pause_auto_scroll()
        self.scroll_page_up(animate=animate)

    def user_scroll_page_down(self, *, animate: bool = True) -> None:
        self.scroll_page_down(
            animate=animate,
            on_complete=self._sync_scroll_state_from_position,
        )
        self.call_after_refresh(self._sync_scroll_state_from_position)

    def user_scroll_home(self, *, animate: bool = True) -> None:
        self.pause_auto_scroll()
        self.scroll_home(
            animate=animate,
            on_complete=self._sync_scroll_state_from_position,
        )

    def user_scroll_end(self, *, animate: bool = False) -> None:
        self.force_scroll_end(animate=animate)

    def append_widget(self, widget: Widget) -> None:
        """Mount a widget and auto-scroll unless user scrolled up."""
        should_follow = self.should_follow_tail()
        widget.styles.offset = (0, -1)
        self.mount(widget)
        try:
            widget.animate('offset', (0, 0), duration=0.2)
        except Exception:
            widget.styles.offset = (0, 0)
        if should_follow:
            self.scroll_end(animate=False)

    def write(self, renderable: Any) -> None:
        """Compatibility method for RichLog interface."""
        self.append_widget(Static(renderable))

    def force_scroll_end(self, *, animate: bool = False) -> None:
        """Scroll to bottom regardless of user scroll state."""
        self._set_user_scrolled_away(False)
        self.scroll_end(animate=animate)

    def clear(self) -> None:
        """Compatibility method for RichLog interface."""
        self.remove_children()
        self._scroll_badge = None
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
