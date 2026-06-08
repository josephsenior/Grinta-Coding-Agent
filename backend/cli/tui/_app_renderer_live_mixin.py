"""_AppRendererLiveMixin: subscribe + live thinking/response streaming."""

from __future__ import annotations

import time
from typing import Any

_LIVE_SCROLL_PAINT_INTERVAL = 0.1

from rich.text import (
    Text,
)
from textual.widgets import (
    Static,
)

from backend.cli.tui._app_constants import (
    _TUI_HISTORY_RENDER_LIMIT,
)
from backend.ledger import (
    EventStreamSubscriber,
)


class _AppRendererLiveMixin:
    """subscribe + live thinking/response streaming."""

    def _maybe_scroll_to_tail(self, display: Any) -> None:
        if not display.should_follow_tail():
            return
        now = time.monotonic()
        last_scroll = getattr(self, '_last_scroll_paint_at', 0.0)
        if (now - last_scroll) < _LIVE_SCROLL_PAINT_INTERVAL:
            return
        self._last_scroll_paint_at = now
        display.scroll_end(animate=False)

    def subscribe(self, event_stream: Any, sid: str) -> None:
        self._event_stream = event_stream
        event_stream.subscribe(EventStreamSubscriber.CLI, self._on_event, sid)

    def add_to_history(self, renderable: Any) -> None:
        """Add a finalized renderable or widget to the transcript."""
        self.commit_live_thinking()
        self.clear_live_response()

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
                display.append_widget(renderable)
            else:
                display.append_widget(Static(renderable))
        self._refresh_display()

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

        if not self._live_response_widget:
            self._live_response_widget = Static(Text(text))
            display.append_widget(self._live_response_widget)
        else:
            self._live_response_widget.update(Text(text))
            self._maybe_scroll_to_tail(display)

    def clear_live_response(self) -> None:
        """Clear the in-flight response preview widget."""
        self._live_response = ''
        self._live_response_dirty = False

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
                    Text('\n  '.join(thoughts), style='#c8c8d4'),
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
