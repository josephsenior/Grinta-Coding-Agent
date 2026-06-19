"""RendererLiveMixin: subscribe + live thinking/response streaming."""

from __future__ import annotations

import contextlib
import time
from typing import Any

from rich.text import (
    Text,
)
from textual.widgets import (
    Static,
)

from backend.cli.theme import CLR_REASONING_SNAP
from backend.cli.tui.constants import (
    _TUI_HISTORY_RENDER_LIMIT,
)
from backend.ledger import (
    EventStreamSubscriber,
)

_LIVE_SCROLL_PAINT_INTERVAL = 0.25
_LIVE_STREAMING_RENDER_INTERVAL = 0.25


def _streaming_render_interval(text: str) -> float:
    from backend.cli.tui.renderer.prep import streaming_render_interval

    return streaming_render_interval(text)


class RendererLiveMixin:
    """subscribe + live thinking/response streaming."""

    def _maybe_scroll_to_tail(self, display: Any) -> None:
        if not display.should_follow_tail():
            return
        now = time.monotonic()
        last_scroll = getattr(self, '_last_scroll_paint_at', 0.0)
        if (now - last_scroll) < _LIVE_SCROLL_PAINT_INTERVAL:
            return
        self._last_scroll_paint_at = now
        follow_tail = getattr(display, 'follow_tail', None)
        if callable(follow_tail):
            follow_tail()
        else:
            display.scroll_end(animate=False)

    def subscribe(self, event_stream: Any, sid: str) -> None:
        if self._event_stream is event_stream:
            return
        old_stream = self._event_stream
        if old_stream is not None:
            with contextlib.suppress(Exception):
                old_stream.unsubscribe(EventStreamSubscriber.CLI, old_stream.sid)
        self._event_stream = event_stream
        with contextlib.suppress(Exception):
            event_stream.unsubscribe(EventStreamSubscriber.CLI, sid)
        event_stream.subscribe(EventStreamSubscriber.CLI, self._on_event, sid)

    def add_to_history(self, renderable: Any) -> None:
        """Add a finalized renderable or widget to the transcript."""
        self.commit_live_thinking()
        self.clear_live_response()
        register = getattr(self, '_register_widget_event_id', None)

        self._history.append(renderable)
        self._history.append(Text(''))
        overflow = len(self._history) - _TUI_HISTORY_RENDER_LIMIT
        if overflow > 0:
            del self._history[:overflow]
            self._history_items_dropped += overflow

        display = self._tui._get_display()
        if type(display).__name__ == 'MagicMock':
            display.write(renderable)
        else:
            from textual.widget import Widget

            if isinstance(renderable, Widget):
                widget = renderable
            else:
                widget = Static(renderable)
            if callable(register):
                register(widget)
            if getattr(self, '_prepend_mode', False):
                display.prepend_widget(widget)
            else:
                display.append_widget(widget)
        self._refresh_display()
        sync = getattr(self, '_sync_transcript_viewport', None)
        if callable(sync):
            sync()
        else:
            prune = getattr(self, '_maybe_prune_transcript', None)
            if callable(prune):
                prune()

    def update_live_thinking(self, text: str) -> None:
        """Update the real-time reasoning preview in-place."""
        self._live_thinking = text
        self._live_thinking_dirty = bool(text.strip())

        if text.strip():
            self._clear_last_active_card_processing()

        display = self._tui._get_display()
        if type(display).__name__ == 'MagicMock':
            display.clear()
            display.write(text)
            return

        if not text.strip():
            return

        should_follow = display.should_follow_tail()
        if not self._live_thinking_widget:
            from backend.cli.tui.widgets.activity_card import ThinkingIndicator

            self._live_thinking_widget = ThinkingIndicator()
            display.append_widget(self._live_thinking_widget)
            self._live_thinking_widget.start()

        self._live_thinking_widget.set_thoughts(text, streaming=True)
        if should_follow:
            self._maybe_scroll_to_tail(display)

    def _apply_live_response_render(self, text: str) -> None:
        from backend.cli.tui.renderer.prep import (
            prep_streaming_renderable,
            streaming_render_cache_key,
        )

        widget = self._live_response_widget
        if widget is None:
            return
        # Reuse an off-thread-prepared renderable when available (filled by
        # prep_streaming_response_async during _preprocess_event_async) so the
        # heavy Pygments/Markdown pass never runs on the Textual event loop.
        cache = getattr(self, '_streaming_render_cache', None)
        renderable = None
        if cache is not None:
            renderable = cache.get(streaming_render_cache_key(text))
        try:
            if renderable is None:
                renderable = prep_streaming_renderable(text)
            widget.set_streaming_renderable(renderable)
        except Exception:
            widget.set_streaming_text(text)

    def _follow_transcript_tail_after_reflow(self, display: Any) -> None:
        """Scroll to tail after in-place widget reflow updates max_scroll_y."""
        if display._user_scrolled_away:
            return

        def _follow_after_reflow() -> None:
            if getattr(display, '_user_scrolled_away', False):
                return
            # call_after_refresh already runs after the layout reflow that
            # updates max_scroll_y, so a single scroll is sufficient. Avoid
            # piling extra call_soon callbacks onto the event loop.
            try:
                display._suppress_scroll_sync = True
                display.scroll_end(animate=False, force=True, immediate=True)
                display.call_after_refresh(display._release_programmatic_scroll)
            except Exception:
                follow_tail = getattr(display, 'follow_tail', None)
                if callable(follow_tail):
                    follow_tail()

        display.call_after_refresh(_follow_after_reflow)

    def _flush_deferred_streaming_render(self) -> None:
        self._streaming_render_timer_armed = False
        text = getattr(self, '_live_response_pending_text', '')
        if not text.strip():
            return
        self._last_streaming_render_at = time.monotonic()
        self._apply_live_response_render(text)
        try:
            display = self._tui._get_display()
        except (AttributeError, Exception):
            return
        if type(display).__name__ != 'MagicMock':
            self._follow_transcript_tail_after_reflow(display)

    def update_live_response(self, text: str) -> None:
        """Update the in-flight assistant response in-place."""
        self._live_response = text
        self._live_response_dirty = bool(text.strip())

        if text.strip():
            self._clear_last_active_card_processing()

        display = self._tui._get_display()
        if type(display).__name__ == 'MagicMock':
            if not self._live_response_dirty:
                self.clear_live_response()
                return
            display.clear()
            display.write(text)
            return

        if not text.strip():
            self.clear_live_response()
            return

        should_follow = display.should_follow_tail()
        in_place_update = self._live_response_widget is not None
        if not self._live_response_widget:
            from backend.cli.tui.widgets.activity_card import LiveResponse

            self._live_response_widget = LiveResponse()
            display.append_widget(self._live_response_widget)

        self._live_response_pending_text = text
        now = time.monotonic()
        last_render = getattr(self, '_last_streaming_render_at', 0.0)
        render_interval = _streaming_render_interval(text)
        if last_render <= 0.0 or (now - last_render) >= render_interval:
            self._last_streaming_render_at = now
            self._streaming_render_timer_armed = False
            self._apply_live_response_render(text)
        elif not getattr(self, '_streaming_render_timer_armed', False):
            self._streaming_render_timer_armed = True
            delay = max(render_interval - (now - last_render), 0.01)
            try:
                self._loop.call_later(delay, self._flush_deferred_streaming_render)
            except RuntimeError:
                self._streaming_render_timer_armed = False
                self._last_streaming_render_at = now
                self._apply_live_response_render(text)
        if should_follow:
            follow_tail = getattr(display, 'follow_tail', None)
            if callable(follow_tail):
                if in_place_update:
                    self._follow_transcript_tail_after_reflow(display)
                else:
                    follow_tail()
            else:
                self._maybe_scroll_to_tail(display)

    def clear_live_response(self) -> None:
        """Clear the in-flight response preview widget."""
        self._live_response = ''
        self._live_response_dirty = False
        self._live_response_pending_text = ''
        self._streaming_render_timer_armed = False
        self._last_streaming_render_at = 0.0

        display = self._tui._get_display()
        if type(display).__name__ == 'MagicMock':
            display.clear()
            return

        if self._live_response_widget:
            self._live_response_widget.remove()
            self._live_response_widget = None

    def commit_live_thinking(self) -> None:
        """Freeze the current live thinking block at its transcript position."""
        display = self._tui._get_display()
        if type(display).__name__ == 'MagicMock':
            if self._live_thinking_dirty:
                if self._live_thinking.strip():
                    self._history.append(self._live_thinking)
                    display.write(self._live_thinking)
            self._live_thinking = ''
            self._live_thinking_dirty = False
            return

        if self._live_thinking_widget:
            thoughts = list(self._live_thinking_widget._thoughts)
            if thoughts and self._live_thinking_dirty:
                self._live_thinking_widget.finalize()
                snapshot = Text.assemble(
                    ('Thinking:', '#42a394'),
                    '  ',
                    Text('\n  '.join(thoughts), style=CLR_REASONING_SNAP),
                )
                self._history.append(snapshot)
                self._history.append(Text(''))
                overflow = len(self._history) - _TUI_HISTORY_RENDER_LIMIT
                if overflow > 0:
                    del self._history[:overflow]
                    self._history_items_dropped += overflow
            else:
                self._live_thinking_widget.remove()
            self._live_thinking_widget = None
            self._live_thinking_dirty = False

            self._live_thinking = ''
            self._live_thinking_dirty = False

    def _finalize_live_thinking(self) -> None:
        finalize = getattr(self._tui, 'finalize_thinking', None)
        if callable(finalize):
            finalize()
        else:
            self.commit_live_thinking()
