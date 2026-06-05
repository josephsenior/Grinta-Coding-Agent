"""Event drain / activity machinery for :class:`_AppRendererEventProcessorMixin`.

Owns:
- ``drain_events`` — atomic flush of the pending event queue into the
  transcript.
- ``wait_for_activity`` — async wait until either new events arrive or the
  timeout fires.
- ``_on_event`` — enqueue an event from any thread, bounded by
  ``_TUI_PENDING_EVENT_LIMIT`` (the test suite monkey-patches this constant
  on the mixin module, so the constant is resolved at call time via a
  deferred import).
- ``_signal_activity`` — wake the activity event and post a
  ``RendererDrainRequested`` message on the TUI loop.
"""

from __future__ import annotations

import asyncio
from functools import partial
from typing import TYPE_CHECKING, Any

from rich.text import Text

from backend.cli.theme import NAVY_TEXT_DIM
from backend.cli.tui._app_small_widgets import RendererDrainRequested

if TYPE_CHECKING:
    from backend.cli.tui._app_renderer_event_processor_mixin import (
        _AppRendererEventProcessorMixin,
    )


def drain_events(orch: '_AppRendererEventProcessorMixin') -> None:
    with orch._pending_lock:
        events = list(orch._pending_events)
        orch._pending_events.clear()
        orch._drain_scheduled = False
        dropped = orch._pending_events_dropped
        orch._pending_events_dropped = 0
    if not events:
        orch._refresh_display()  # Keep sidebar/HUD in sync
        return
    if dropped:
        # Deferred import: the test suite patches this constant on the mixin
        # module via ``monkeypatch.setattr(_ep_mod, '_TUI_HISTORY_RENDER_LIMIT', ...)``.
        from backend.cli.tui._app_renderer_event_processor_mixin import (
            _TUI_HISTORY_RENDER_LIMIT,
        )

        orch._history.append(
            Text(
                f'... {dropped} TUI event(s) dropped while the renderer was backlogged ...',
                style=NAVY_TEXT_DIM,
            )
        )
        orch._history.append(Text(''))
        overflow = len(orch._history) - _TUI_HISTORY_RENDER_LIMIT
        if overflow > 0:
            del orch._history[:overflow]
    for event in events:
        orch._process_event(event)
    orch._refresh_display()


async def wait_for_activity(
    orch: '_AppRendererEventProcessorMixin',
    wait_timeout_sec: float = 0.5,
) -> Any:
    with orch._pending_lock:
        has_pending = bool(orch._pending_events)
    if has_pending:
        drain_events(orch)
        orch._state_event.clear()
        return orch._current_state
    try:
        await asyncio.wait_for(orch._state_event.wait(), timeout=wait_timeout_sec)
    except TimeoutError:
        return None
    finally:
        orch._state_event.clear()
    drain_events(orch)
    return orch._current_state


def _on_event(orch: '_AppRendererEventProcessorMixin', event: Any) -> None:
    # Deferred import: the test suite monkey-patches this constant on the
    # mixin module (``monkeypatch.setattr(_ep_mod, '_TUI_PENDING_EVENT_LIMIT', N)``).
    from backend.cli.tui._app_renderer_event_processor_mixin import (
        _TUI_PENDING_EVENT_LIMIT,
    )

    should_schedule_drain = False
    with orch._pending_lock:
        if len(orch._pending_events) >= _TUI_PENDING_EVENT_LIMIT:
            orch._pending_events.popleft()
            orch._pending_events_dropped += 1
        orch._pending_events.append(event)
        if not orch._drain_scheduled:
            orch._drain_scheduled = True
            should_schedule_drain = True
    try:
        orch._loop.call_soon_threadsafe(
            partial(_signal_activity, orch),
            should_schedule_drain,
        )
    except RuntimeError:
        pass


def _signal_activity(
    orch: '_AppRendererEventProcessorMixin',
    should_schedule_drain: bool,
) -> None:
    orch._state_event.set()
    if not should_schedule_drain:
        return
    try:
        orch._tui.post_message(RendererDrainRequested())
    except Exception:
        with orch._pending_lock:
            orch._drain_scheduled = False
