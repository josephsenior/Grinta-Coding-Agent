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


class ScrollTailBadge(Static):
    """Clickable chip shown when the user scrolls away from live transcript tail."""

    DEFAULT_CSS = """
    ScrollTailBadge {
        dock: bottom;
        width: 100%;
        height: 1;
        content-align: center middle;
        background: #08101d;
        color: #91abec;
        border-top: solid #1b233a;
    }
    ScrollTailBadge:hover {
        background: #0a1323;
        color: #c8d4e8;
    }
    ScrollTailBadge:focus {
        background: #0d162a;
        color: #ffffff;
        border-top: solid #5eead4;
    }
    ScrollTailBadge.-hidden {
        display: none;
    }
    """

    class FollowRequested(Message):
        """User clicked or activated the follow-live chip."""

    def __init__(self) -> None:
        super().__init__('', id='scroll-badge', classes='-hidden')
        self.can_focus = True
        self._unread_count = 0

    def set_unread_count(self, count: int) -> None:
        self._unread_count = max(0, count)
        if self._unread_count <= 0:
            self.update('[#91abec]↓ Follow live[/]')
        elif self._unread_count == 1:
            self.update('[#91abec]↓[/] [#c8d4e8]1 new update[/]')
        else:
            self.update(f'[#91abec]↓[/] [#c8d4e8]{self._unread_count} new updates[/]')

    def on_click(self, event: events.Click) -> None:
        self.post_message(self.FollowRequested())
        event.prevent_default()
        event.stop()

    def on_key(self, event: events.Key) -> None:
        if event.key in ('enter', 'space'):
            self.post_message(self.FollowRequested())
            event.prevent_default()
            event.stop()


class InfoSidebar(VerticalScroll):
    """Sidebar for Mission Control info (Tasks, MCPs, Skills)."""

    def update(self, *args: Any, **kwargs: Any) -> None:
        """No-op update for backward compatibility and test mock compatibility."""
        pass


class Transcript(VerticalScroll):
    """Scrollable conversation transcript container with auto-scroll awareness."""

    # Single source of truth for the mounted-widget cap. The legacy prune path
    # in RendererDisplayMixin reads ``display._VIEWPORT_MAX_MOUNTED``; keep it in
    # sync with the env-overridable constant resolved at import time.
    from backend.cli.tui.constants import (
        _TUI_VIEWPORT_MAX_MOUNTED as _VIEWPORT_MAX_MOUNTED,
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._user_scrolled_away = False
        self._user_initiated_scroll_away = False
        self._scroll_badge: ScrollTailBadge | None = None
        self._tail_unread_count = 0
        self._suppress_mount_animation = False
        self._under_backpressure = False
        self._suppress_scroll_sync = False
        self._last_scroll_y = 0.0
        self._last_max_scroll_y = 0.0
        self._load_earlier_button: Static | None = None

    def compose(self) -> ComposeResult:
        yield ScrollTailBadge()

    def on_mount(self) -> None:
        self._scroll_badge = self.query_one('#scroll-badge', ScrollTailBadge)

    def _update_scroll_badge(self) -> None:
        badge = self._scroll_badge
        if badge is None:
            return
        badge.set_unread_count(self._tail_unread_count)

    def _was_at_bottom(self, threshold: float = 0.5) -> bool:
        if self.max_scroll_y <= 0:
            return True
        current_distance = self.max_scroll_y - self.scroll_y
        if self._user_scrolled_away:
            return current_distance <= threshold
        target_distance = self.max_scroll_y - self.scroll_target_y
        return current_distance <= threshold or target_distance <= threshold

    def _set_user_scrolled_away(self, value: bool) -> None:
        self._user_scrolled_away = value
        if not value:
            self._user_initiated_scroll_away = False
            self._tail_unread_count = 0
        badge = self._scroll_badge
        if badge is None:
            return
        self._update_scroll_badge()
        if value:
            badge.remove_class('-hidden')
        else:
            badge.add_class('-hidden')

    def note_tail_activity(self) -> None:
        """Record new transcript content while the user is not following the tail."""
        if not self._user_scrolled_away:
            return
        self._tail_unread_count += 1
        self._update_scroll_badge()

    def on_scroll_tail_badge_follow_requested(
        self, event: ScrollTailBadge.FollowRequested
    ) -> None:
        event.stop()
        self.force_scroll_end()

    def _sync_scroll_state_from_position(self) -> None:
        """Update follow-tail state from scroll position.

        Content growth increases max_scroll_y while scroll_y stays put; that
        must not be treated as the user leaving the tail. Only upward movement
        (or already being away from the bottom without fresh content) counts.
        """
        max_y = self.max_scroll_y
        scroll_y = self.scroll_y
        last_max_y = self._last_max_scroll_y
        last_scroll_y = self._last_scroll_y
        self._last_max_scroll_y = max_y
        self._last_scroll_y = scroll_y

        if self._user_scrolled_away:
            if self._was_at_bottom() and scroll_y > last_scroll_y + 0.5:
                self._set_user_scrolled_away(False)
            return

        if max_y > last_max_y:
            return

    def set_backpressure(self, active: bool) -> None:
        """Mark whether the renderer is draining a backlog.

        While active, ``append_widget`` skips its mount animation so bursts
        of cards mount instantly instead of queueing 0.2s animations on the
        event loop, which otherwise causes visible freezes during streaming.
        """
        self._under_backpressure = bool(active)

    def should_follow_tail(self) -> bool:
        """Return True when live updates should keep the transcript pinned.

        Only explicit user scroll-away actions set _user_scrolled_away.
        During agentic activity the scroll position briefly lags behind
        max_scroll_y while new content mounts; that lag must not disable follow.
        """
        return not self._user_scrolled_away

    def pause_auto_scroll(self) -> None:
        """Stop live updates from pulling the transcript back to the bottom.

        Triggered by genuine user scroll input, so it must register the
        scroll-away even while a programmatic follow-tail scroll is in
        progress (``_suppress_scroll_sync`` True). Otherwise rapid streaming
        keeps the suppression flag set and the user's scroll is ignored.
        """
        if self.max_scroll_y > 0:
            self._user_initiated_scroll_away = True
            self._set_user_scrolled_away(True)

    def _content_widgets(self) -> list[Widget]:
        widgets: list[Widget] = []
        for child in self.children:
            if child is self._scroll_badge:
                continue
            if child is self._load_earlier_button:
                continue
            widgets.append(child)
        return widgets

    def sync_viewport(self, renderer: Any) -> None:
        """Unmount off-viewport widgets while retaining render cache for replay."""
        from backend.cli.tui.constants import _TUI_VIEWPORT_MAX_MOUNTED
        from backend.cli.tui.renderer.prep import RenderArtifact

        widgets = self._content_widgets()
        max_mounted = _TUI_VIEWPORT_MAX_MOUNTED
        if len(widgets) <= max_mounted:
            return

        overflow = len(widgets) - max_mounted
        if self.should_follow_tail():
            to_unmount = widgets[:overflow]
        else:
            to_unmount = widgets[-overflow:]

        cache = getattr(renderer, '_render_cache', None)
        for widget in to_unmount:
            event_id = getattr(widget, '_ledger_event_id', None)
            if cache is not None and event_id is not None:
                cache[event_id] = RenderArtifact(
                    event_id,
                    widget,
                    measured_height=max(getattr(widget, 'size', None).height, 1)
                    if getattr(widget, 'size', None)
                    else 1,
                )
            try:
                widget.remove()
            except Exception:
                pass

    def _maybe_prefetch_earlier(self) -> None:
        if not self._user_scrolled_away:
            return
        if self.scroll_y > 80:
            return
        try:
            self.post_message(LoadEarlierRequested())
        except Exception:
            pass

    def on_scroll(self, _event: Widget.Scroll) -> None:
        if self._suppress_scroll_sync:
            return
        self._sync_scroll_state_from_position()
        self._maybe_prefetch_earlier()

    def _on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        # Register the user scroll-away before delegating, and bypass the
        # programmatic-scroll guard so an in-flight follow-tail cannot
        # swallow this input during active streaming.
        self._suppress_scroll_sync = False
        self.pause_auto_scroll()
        super()._on_mouse_scroll_up(event)

    def _on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        super()._on_mouse_scroll_down(event)
        self.call_after_refresh(self._sync_scroll_state_from_position)

    def user_scroll_page_up(self, *, animate: bool = True) -> None:
        self._suppress_scroll_sync = False
        self.pause_auto_scroll()
        self.scroll_page_up(animate=animate)

    def user_scroll_page_down(self, *, animate: bool = True) -> None:
        self.scroll_page_down(
            animate=animate,
            on_complete=self._sync_scroll_state_from_position,
        )
        self.call_after_refresh(self._sync_scroll_state_from_position)

    def user_scroll_home(self, *, animate: bool = True) -> None:
        self._suppress_scroll_sync = False
        self.pause_auto_scroll()
        self.scroll_home(
            animate=animate,
            on_complete=self._sync_scroll_state_from_position,
        )

    def user_scroll_end(self, *, animate: bool = False) -> None:
        self.force_scroll_end(animate=animate)

    def follow_tail(self) -> None:
        """Pin the transcript to the latest content when the user is following."""
        if self._user_scrolled_away:
            return
        self._schedule_follow_tail()

    def _schedule_follow_tail(self) -> None:
        """Scroll after layout refresh so max_scroll_y reflects new children."""

        def _scroll_after_layout() -> None:
            if self._user_scrolled_away:
                return
            self._suppress_scroll_sync = True
            self.scroll_end(animate=False, force=True, immediate=True)
            self.call_after_refresh(self._release_programmatic_scroll)

        self.call_after_refresh(_scroll_after_layout)

    def _release_programmatic_scroll(self) -> None:
        self._suppress_scroll_sync = False
        self._sync_scroll_state_from_position()
        if self._was_at_bottom() and not self._user_initiated_scroll_away:
            self._set_user_scrolled_away(False)

    def append_widget(self, widget: Widget, *, animate: bool | None = None) -> None:
        """Mount a widget and auto-scroll unless user scrolled up."""
        should_follow = self.should_follow_tail()
        use_animation = (
            animate
            if animate is not None
            else not (
                getattr(self, '_suppress_mount_animation', False)
                or getattr(self, '_under_backpressure', False)
            )
        )
        if use_animation:
            widget.styles.offset = (0, -1)
        self.mount(widget)
        if use_animation:
            try:
                widget.animate('offset', (0, 0), duration=0.2)
            except Exception:
                widget.styles.offset = (0, 0)
        if should_follow:
            self._schedule_follow_tail()
        else:
            self.note_tail_activity()

    def write(self, renderable: Any) -> None:
        """Compatibility method for RichLog interface."""
        self.append_widget(Static(renderable))

    def force_scroll_end(self, *, animate: bool = False) -> None:
        """Scroll to bottom regardless of user scroll state."""
        self._set_user_scrolled_away(False)
        self._suppress_scroll_sync = True
        self.scroll_end(animate=animate, force=True, immediate=not animate)
        self.call_after_refresh(self._release_programmatic_scroll)

    def clear(self) -> None:
        """Compatibility method for RichLog interface."""
        self.remove_children()
        self._scroll_badge = None
        self._user_scrolled_away = False
        self._user_initiated_scroll_away = False
        self._load_earlier_button = None
        self._tail_unread_count = 0
        self.mount(ScrollTailBadge())
        self._scroll_badge = self.query_one('#scroll-badge', ScrollTailBadge)

    @property
    def child_widget_count(self) -> int:
        """Count of content widgets (excludes system widgets like scroll-badge)."""
        count = 0
        for child in self.children:
            if child is self._scroll_badge:
                continue
            if child is self._load_earlier_button:
                continue
            count += 1
        return count

    def prune_oldest(self, count: int) -> int:
        """Unmount the N oldest content widgets. Returns count of widgets removed."""
        removed = 0
        for child in list(self.children):
            if removed >= count:
                break
            if child is self._scroll_badge:
                continue
            if child is self._load_earlier_button:
                continue
            try:
                child.remove()
                removed += 1
            except Exception:
                pass
        return removed

    def set_load_earlier_button(self, button: Static | None) -> None:
        """Set or clear the 'load earlier messages' button reference."""
        self._load_earlier_button = button

    def prepend_widget(self, widget: Widget) -> None:
        """Mount a widget at the top of the transcript (after system widgets)."""
        button = self._load_earlier_button
        if button is not None and button in self.children:
            try:
                self.mount(widget, after=button)
                return
            except Exception:
                pass
        if self._scroll_badge is not None and self._scroll_badge in self.children:
            try:
                self.mount(widget, after=self._scroll_badge)
                return
            except Exception:
                pass
        self.mount(widget)


class InputBar(Horizontal):
    """Bottom input row with border and prompt."""


class PromptTextArea(TextArea):
    """Input area that routes arrow navigation to welcome suggestions when idle."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._previous_input_text = ''

    def _paste_target_screen(self) -> Any | None:
        app = getattr(self, 'app', None)
        screen = getattr(app, 'screen', None) if app is not None else None
        if screen is not None:
            return screen
        return getattr(self, 'screen', None)

    def watch_text(self, text: str) -> None:
        previous = self._previous_input_text
        self._previous_input_text = text
        screen = self._paste_target_screen()
        if screen is None:
            return
        if previous.strip() and not text.strip():
            pending = getattr(screen, '_pending_image_urls', None)
            if pending:
                screen._pending_image_urls = []
        refresh = getattr(screen, '_refresh_input_attachment_hint', None)
        if callable(refresh):
            refresh()

    def _paste_text_from_clipboard(self, event: events.Paste | None = None) -> None:
        try:
            clipboard = pyperclip.paste()
        except Exception:
            clipboard = event.text if event is not None else ''
        if result := self._replace_via_keyboard(clipboard, *self.selection):
            self.move_cursor(result.end_location)

    async def _on_paste(self, event: events.Paste) -> None:
        """Paste text or attach a clipboard image when available."""
        if self.read_only:
            return
        screen = self._paste_target_screen()
        if screen is not None and hasattr(screen, 'try_paste_clipboard_image'):
            if screen.try_paste_clipboard_image():
                event.prevent_default()
                event.stop()
                return
        event.prevent_default()
        self._paste_text_from_clipboard(event)

    def action_paste(self) -> None:
        """Paste from system clipboard directly."""
        if self.read_only:
            return
        screen = self._paste_target_screen()
        if screen is not None and hasattr(screen, 'try_paste_clipboard_image'):
            if screen.try_paste_clipboard_image():
                return
        try:
            pyperclip.paste()
        except Exception:
            return super().action_paste()
        self._paste_text_from_clipboard()

    def on_key(self, event: events.Key) -> None:
        screen = getattr(self, 'screen', None)
        if event.key in {'pageup', 'pagedown'} and screen is not None:
            if event.key == 'pageup' and hasattr(screen, 'action_scroll_up'):
                screen.action_scroll_up()
            elif event.key == 'pagedown' and hasattr(screen, 'action_scroll_down'):
                screen.action_scroll_down()
            event.prevent_default()
            event.stop()
            return
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


class HudModeSelect(Select):
    """Mode picker that propagates programmatic value changes to the screen."""

    def watch_value(self, value: object) -> None:
        if value is Select.BLANK:
            return
        screen = self.screen
        if screen is None:
            return
        if not getattr(screen, '_hud_controls_ready', False):
            return
        if getattr(screen, '_hud_mode_syncing', False):
            return
        active_config = getattr(screen, '_active_agent_config', None)
        if callable(active_config):
            agent_config = active_config()
            if agent_config is not None and getattr(agent_config, 'mode', None) == str(
                value
            ):
                return
        apply_mode = getattr(screen, '_apply_mode', None)
        if callable(apply_mode):
            apply_mode(str(value))


class HUD(Vertical):
    """Multi-line status bar at the very bottom."""

    def compose(self) -> ComposeResult:
        with Horizontal(id='hud-line-2-row'):
            yield Label('[#7a6a4a]Mode:[/]', id='hud-label-mode')
            yield HudModeSelect(
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
        with Horizontal(id='hud-line-1-row'):
            yield Label(id='hud-line-1')
            yield Label('[#969aad]Model:[/]', id='hud-label-model')
            yield Label(id='hud-model-name')
            yield Label('[#969aad]Reasoning:[/]', id='hud-label-reasoning')
            yield Select(
                [('Default', '')],
                value='',
                id='hud-reasoning',
                allow_blank=False,
            )
            yield Label(id='hud-line-1-ws')


class RendererDrainRequested(Message):
    """Message requesting the screen to drain queued renderer events."""


class LoadEarlierRequested(Message):
    """Message requesting the screen to load earlier messages from the ledger."""


class LoadEarlierButton(Static):
    """Button that appears at the top of the transcript when older messages exist."""

    DEFAULT_CSS = """
    LoadEarlierButton {
        width: 100%;
        height: 1;
        content-align: center middle;
        color: #8f9fc1;
        background: #08101d;
        margin: 0 0 1 0;
    }
    LoadEarlierButton:hover {
        color: #91abec;
        background: #0a1323;
    }
    """

    def __init__(self) -> None:
        super().__init__('Load earlier messages')
        self.can_focus = True

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.post_message(LoadEarlierRequested())

    def on_key(self, event: events.Key) -> None:
        if event.key in ('enter', 'space'):
            event.stop()
            self.post_message(LoadEarlierRequested())
