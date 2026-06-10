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

_TUI_DRAIN_DEBOUNCE_SECONDS = 0.016


def _is_streaming_only_batch(events: list[Any]) -> bool:
    from backend.ledger.action.message import StreamingChunkAction

    return bool(events) and all(
        isinstance(event, StreamingChunkAction) for event in events
    )


def _collapse_streaming_chunks(events: list[Any]) -> list[Any]:
    """Keep only the latest snapshot from each run of streaming chunk events."""
    from backend.ledger.action.message import StreamingChunkAction

    if not events:
        return events

    collapsed: list[Any] = []
    idx = 0
    while idx < len(events):
        event = events[idx]
        if isinstance(event, StreamingChunkAction):
            end = idx + 1
            while end < len(events) and isinstance(events[end], StreamingChunkAction):
                end += 1
            collapsed.append(events[end - 1])
            idx = end
        else:
            collapsed.append(event)
            idx += 1
    return collapsed


def _try_coalesce_streaming_enqueue(pending: Any, event: Any) -> bool:
    """Replace the tail interim streaming chunk instead of enqueueing another."""
    from backend.ledger.action.message import StreamingChunkAction

    if not isinstance(event, StreamingChunkAction) or not pending:
        return False
    last = pending[-1]
    if not isinstance(last, StreamingChunkAction):
        return False
    if last.is_final:
        return False
    pending[-1] = event
    return True


def drain_events(orch: '_AppRendererEventProcessorMixin') -> None:
    """Synchronous drain for non-async contexts (backward compatibility)."""
    with orch._pending_lock:
        events = list(orch._pending_events)
        orch._pending_events.clear()
        orch._drain_scheduled = False
        dropped = orch._pending_events_dropped
        orch._pending_events_dropped = 0
    if not events:
        flush = getattr(orch, 'flush_live_ui', None)
        if callable(flush):
            flush()
        orch._refresh_display()
        return
    if dropped:
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
    events = _collapse_streaming_chunks(events)
    streaming_only = _is_streaming_only_batch(events)
    for event in events:
        orch._process_event(event)
    flush = getattr(orch, 'flush_live_ui', None)
    if callable(flush):
        flush()
    if not streaming_only or any(
        getattr(event, 'is_final', False) for event in events
    ):
        orch._refresh_display(skip_sidebar=streaming_only)


def _cancel_drain_debounce(orch: '_AppRendererEventProcessorMixin') -> None:
    debounce_handle = getattr(orch, '_drain_debounce_handle', None)
    if debounce_handle is not None:
        try:
            debounce_handle.cancel()
        except Exception:
            pass
        orch._drain_debounce_handle = None


def _collect_pending_events(orch: '_AppRendererEventProcessorMixin') -> tuple[list[Any], int]:
    with orch._pending_lock:
        events = list(orch._pending_events)
        orch._pending_events.clear()
        orch._drain_scheduled = False
        dropped = orch._pending_events_dropped
        orch._pending_events_dropped = 0
    return events, dropped


def _record_dropped_events(orch: '_AppRendererEventProcessorMixin', dropped: int) -> None:
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


def _flush_and_refresh(
    orch: '_AppRendererEventProcessorMixin',
    events: list[Any],
    streaming_only: bool,
) -> None:
    flush = getattr(orch, 'flush_live_ui', None)
    if callable(flush):
        flush()
    if not streaming_only or any(
        getattr(event, 'is_final', False) for event in events
    ):
        orch._refresh_display(skip_sidebar=streaming_only)


async def _process_events_in_batches(
    orch: '_AppRendererEventProcessorMixin',
    events: list[Any],
) -> None:
    _BATCH_SIZE = 10
    for i in range(0, len(events), _BATCH_SIZE):
        batch = events[i:i + _BATCH_SIZE]
        for event in batch:
            orch._process_event(event)
        await asyncio.sleep(0)


async def drain_events_async(orch: '_AppRendererEventProcessorMixin') -> None:
    """Async drain that yields control to the event loop periodically.
    
    This prevents blocking the Textual event loop when processing many events,
    allowing keyboard and mouse input to be processed during active agent runs.
    """
    _cancel_drain_debounce(orch)

    events, dropped = _collect_pending_events(orch)
    if not events:
        flush = getattr(orch, 'flush_live_ui', None)
        if callable(flush):
            flush()
        orch._refresh_display()
        return
    if dropped:
        _record_dropped_events(orch, dropped)

    events = _collapse_streaming_chunks(events)
    streaming_only = _is_streaming_only_batch(events)

    await _process_events_in_batches(orch, events)
    _flush_and_refresh(orch, events, streaming_only)


async def wait_for_activity(
    orch: '_AppRendererEventProcessorMixin',
    wait_timeout_sec: float = 0.5,
) -> Any:
    with orch._pending_lock:
        has_pending = bool(orch._pending_events)
    if has_pending:
        await drain_events_async(orch)
        orch._state_event.clear()
        return orch._current_state
    try:
        await asyncio.wait_for(orch._state_event.wait(), timeout=wait_timeout_sec)
    except TimeoutError:
        return None
    finally:
        orch._state_event.clear()
    await drain_events_async(orch)
    return orch._current_state


_LOAD_EARLIER_BATCH_SIZE = 100


async def load_earlier_messages(
    orch: '_AppRendererEventProcessorMixin',
    batch_size: int = _LOAD_EARLIER_BATCH_SIZE,
) -> int:
    """Fetch and render earlier events from the ledger.

    Returns the number of events loaded, or 0 if no earlier events exist.
    """
    min_id = orch._min_rendered_event_id
    if min_id <= 0:
        return 0
    event_stream = getattr(orch, '_event_stream', None)
    if event_stream is None:
        return 0

    start_id = max(0, min_id - batch_size)
    try:
        events = list(event_stream.search_events(
            start_id=start_id,
            end_id=min_id,
            reverse=False,
        ))
    except Exception:
        return 0

    if not events:
        return 0

    orch._replay_mode = True
    orch._prepend_mode = True
    try:
        for event in events:
            orch._process_event(event)
        flush = getattr(orch, 'flush_live_ui', None)
        if callable(flush):
            flush()
        orch._refresh_display()
    finally:
        orch._replay_mode = False
        orch._prepend_mode = False

    if events:
        first_id = getattr(events[0], 'id', -1)
        if first_id >= 0:
            orch._min_rendered_event_id = first_id

    return len(events)


def _on_event(orch: '_AppRendererEventProcessorMixin', event: Any) -> None:
    # Deferred import: the test suite monkey-patches this constant on the
    # mixin module (``monkeypatch.setattr(_ep_mod, '_TUI_PENDING_EVENT_LIMIT', N)``).
    from backend.cli.tui._app_renderer_event_processor_mixin import (
        _TUI_PENDING_EVENT_LIMIT,
    )

    event_id = getattr(event, 'id', -1)
    should_schedule_drain = False
    with orch._pending_lock:
        if event_id >= 0:
            if orch._min_rendered_event_id < 0 or event_id < orch._min_rendered_event_id:
                orch._min_rendered_event_id = event_id
            if event_id > orch._max_rendered_event_id:
                orch._max_rendered_event_id = event_id
        coalesced = _try_coalesce_streaming_enqueue(orch._pending_events, event)
        if not coalesced:
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


def _post_drain_message(orch: '_AppRendererEventProcessorMixin') -> None:
    orch._drain_debounce_handle = None
    try:
        orch._tui.post_message(RendererDrainRequested())
    except Exception:
        with orch._pending_lock:
            orch._drain_scheduled = False


def _signal_activity(
    orch: '_AppRendererEventProcessorMixin',
    should_schedule_drain: bool,
) -> None:
    orch._state_event.set()
    if not should_schedule_drain:
        return
    if getattr(orch, '_drain_debounce_handle', None) is not None:
        return
    try:
        orch._drain_debounce_handle = orch._loop.call_later(
            _TUI_DRAIN_DEBOUNCE_SECONDS,
            lambda: _post_drain_message(orch),
        )
    except Exception:
        with orch._pending_lock:
            orch._drain_scheduled = False
