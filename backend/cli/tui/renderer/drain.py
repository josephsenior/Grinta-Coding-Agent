"""Event drain / activity machinery for :class:`RendererEventProcessorMixin`.

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
import time
from functools import partial
from typing import TYPE_CHECKING, Any

from rich.text import Text

from backend.cli.theme import NAVY_TEXT_DIM
from backend.cli.tui.constants import (
    _TUI_DRAIN_FRAME_BUDGET_SECONDS,
    _TUI_DRAIN_INVOCATION_BUDGET_SECONDS,
    _tui_logger,
)
from backend.cli.tui.widgets.small import RendererDrainRequested

if TYPE_CHECKING:
    from backend.cli.tui.renderer.mixins.event_processor import (
        RendererEventProcessorMixin,
    )

_TUI_DRAIN_DEBOUNCE_SECONDS = 0.016


def _set_display_backpressure(
    orch: 'RendererEventProcessorMixin', active: bool
) -> None:
    """Propagate drain backpressure to the transcript display widget.

    Skips mount animations during streaming bursts to avoid event-loop
    freezes. No-op for mock displays or displays without the hook.
    """
    try:
        display = orch._tui._get_display()
    except (AttributeError, Exception):
        return
    if type(display).__name__ == 'MagicMock':
        return
    set_backpressure = getattr(display, 'set_backpressure', None)
    if callable(set_backpressure):
        try:
            set_backpressure(active)
        except Exception:
            pass


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


def _try_coalesce_terminal_enqueue(pending: Any, event: Any) -> bool:
    """Collapse consecutive terminal observations for the same session."""
    from backend.ledger.observation.terminal import TerminalObservation

    if not isinstance(event, TerminalObservation) or not pending:
        return False
    session_id = (event.session_id or '').strip()
    if not session_id:
        return False
    for idx in range(len(pending) - 1, -1, -1):
        candidate = pending[idx]
        if not isinstance(candidate, TerminalObservation):
            continue
        if (candidate.session_id or '').strip() != session_id:
            continue
        pending[idx] = event
        return True
    return False


def _coalesce_pending_backlog(pending: Any) -> int:
    """Merge adjacent streaming/terminal events; return slots reclaimed."""
    from backend.ledger.action.message import StreamingChunkAction
    from backend.ledger.observation.terminal import TerminalObservation

    if len(pending) < 2:
        return 0
    reclaimed = 0
    idx = 1
    while idx < len(pending):
        prev = pending[idx - 1]
        cur = pending[idx]
        if isinstance(prev, StreamingChunkAction) and isinstance(
            cur, StreamingChunkAction
        ):
            pending[idx - 1] = cur
            del pending[idx]
            reclaimed += 1
            continue
        if isinstance(prev, TerminalObservation) and isinstance(
            cur, TerminalObservation
        ):
            if (prev.session_id or '') == (cur.session_id or ''):
                pending[idx - 1] = cur
                del pending[idx]
                reclaimed += 1
                continue
        idx += 1
    return reclaimed


def _is_low_value_backlog_event(event: Any) -> bool:
    """Return True for events that are safe to skip under TUI pressure."""
    name = type(event).__name__
    if name in {
        'AgentThinkAction',
        'AgentThinkObservation',
        'NullObservation',
        'StatusObservation',
        'TerminalObservation',
    }:
        return True
    if name == 'StreamingChunkAction':
        return not bool(getattr(event, 'is_final', False))
    return False


def _drop_one_pending_event_for_backpressure(pending: Any) -> bool:
    """Drop one queued event, preferring stale progress noise over milestones."""
    if not pending:
        return False
    for idx, event in enumerate(pending):
        if _is_low_value_backlog_event(event):
            del pending[idx]
            return True
    pending.popleft()
    return True


def _make_backpressure_room(
    orch: 'RendererEventProcessorMixin',
    pending: Any,
    limit: int,
) -> bool:
    """Keep the pending queue bounded before appending a new event."""
    if limit <= 0 or len(pending) < limit:
        return False

    reclaimed = _coalesce_pending_backlog(pending)
    if reclaimed:
        orch._pending_backpressure_reclaimed = (
            getattr(orch, '_pending_backpressure_reclaimed', 0) + reclaimed
        )
        if len(pending) < limit:
            return True

    dropped = 0
    while len(pending) >= limit:
        if not _drop_one_pending_event_for_backpressure(pending):
            break
        dropped += 1

    if dropped:
        orch._pending_events_dropped += dropped
        orch._pending_backpressure = True
    return bool(reclaimed or dropped)


def _force_immediate_drain(orch: 'RendererEventProcessorMixin') -> None:
    handle = getattr(orch, '_drain_debounce_handle', None)
    if handle is not None:
        try:
            handle.cancel()
        except Exception:
            pass
        orch._drain_debounce_handle = None
    _post_drain_message(orch)


def drain_events(orch: 'RendererEventProcessorMixin') -> None:
    """Synchronous drain for non-async contexts (backward compatibility)."""
    with orch._pending_lock:
        events = list(orch._pending_events)
        orch._pending_events.clear()
        orch._drain_scheduled = False
        dropped = orch._pending_events_dropped
        orch._pending_events_dropped = 0
        orch._pending_backpressure = False
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
    for event in events:
        orch._process_event(event)
    flush = getattr(orch, 'flush_live_ui', None)
    if callable(flush):
        flush()
    flush_sync = getattr(orch, 'flush_pending_final_commits_sync', None)
    if callable(flush_sync):
        flush_sync()
    if not streaming_only or any(getattr(event, 'is_final', False) for event in events):
        orch._refresh_display(skip_sidebar=streaming_only)


def _cancel_drain_debounce(orch: 'RendererEventProcessorMixin') -> None:
    debounce_handle = getattr(orch, '_drain_debounce_handle', None)
    if debounce_handle is not None:
        try:
            debounce_handle.cancel()
        except Exception:
            pass
        orch._drain_debounce_handle = None


def _collect_pending_events(
    orch: 'RendererEventProcessorMixin',
) -> tuple[list[Any], int]:
    with orch._pending_lock:
        events = list(orch._pending_events)
        orch._pending_events.clear()
        orch._drain_scheduled = False
        dropped = orch._pending_events_dropped
        orch._pending_events_dropped = 0
        orch._pending_backpressure = False
    return events, dropped


def _record_dropped_events(orch: 'RendererEventProcessorMixin', dropped: int) -> None:
    notice = Text(
        f'... {dropped} stale TUI event(s) skipped while the renderer caught up ...',
        style=NAVY_TEXT_DIM,
    )
    add_to_history = getattr(orch, 'add_to_history', None)
    if callable(add_to_history):
        try:
            add_to_history(notice)
            return
        except Exception:
            pass

    from backend.cli.tui.renderer.mixins.event_processor import (
        _TUI_HISTORY_RENDER_LIMIT,
    )

    orch._history.append(notice)
    orch._history.append(Text(''))
    overflow = len(orch._history) - _TUI_HISTORY_RENDER_LIMIT
    if overflow > 0:
        del orch._history[:overflow]


def _flush_and_refresh(
    orch: 'RendererEventProcessorMixin',
    events: list[Any],
    streaming_only: bool,
    *,
    skip_sidebar: bool | None = None,
) -> None:
    flush = getattr(orch, 'flush_live_ui', None)
    if callable(flush):
        flush()
    if skip_sidebar is None:
        skip_sidebar = streaming_only
    if not streaming_only or any(getattr(event, 'is_final', False) for event in events):
        orch._refresh_display(skip_sidebar=skip_sidebar)


async def _preprocess_event_async(
    orch: 'RendererEventProcessorMixin', event: Any
) -> None:
    """Run heavy prep off the UI thread before synchronous dispatch."""
    event_id = getattr(event, 'id', -1)
    if event_id < 0:
        return
    cache = getattr(orch, '_render_prep_cache', None)
    if cache is None:
        return
    if event_id in cache:
        return

    from backend.cli.tui.renderer.prep import prep_file_edit_encoded_diff_async
    from backend.ledger.observation.files import FileEditObservation

    if not isinstance(event, FileEditObservation):
        return
    encoded = await prep_file_edit_encoded_diff_async(orch, event)
    if encoded:
        cache[event_id] = encoded


async def _process_events_with_frame_budget(
    orch: 'RendererEventProcessorMixin',
    events: list[Any],
) -> int:
    """Process events until the frame budget elapses. Returns count processed."""
    started = time.monotonic()
    processed = 0
    for event in events:
        await _preprocess_event_async(orch, event)
        orch._process_event(event)
        processed += 1
        if (time.monotonic() - started) >= _TUI_DRAIN_FRAME_BUDGET_SECONDS:
            break
    return processed


async def _finalize_drain_pass(orch: 'RendererEventProcessorMixin') -> None:
    flush = getattr(orch, 'flush_live_ui', None)
    if callable(flush):
        flush()
    flush_commits = getattr(orch, 'flush_pending_final_commits', None)
    if callable(flush_commits):
        await flush_commits()
    orch._refresh_display()


async def drain_events_async(orch: 'RendererEventProcessorMixin') -> None:
    """Async drain that yields control to the event loop periodically.

    Processes multiple micro-batches per invocation up to a wall-clock cap so
    backlog drains faster without monopolizing the Textual event loop.
    """
    if getattr(orch, '_async_drain_active', False):
        orch._drain_requested_while_active = True
        return

    _cancel_drain_debounce(orch)
    invocation_started = time.monotonic()
    orch._async_drain_active = True
    last_batch: list[Any] = []
    last_streaming_only = False

    try:
        while True:
            events, dropped = _collect_pending_events(orch)
            if not events:
                await _finalize_drain_pass(orch)
                return
            if dropped:
                _record_dropped_events(orch, dropped)

            events = _collapse_streaming_chunks(events)
            streaming_only = _is_streaming_only_batch(events)
            last_batch = events
            last_streaming_only = streaming_only

            processed = await _process_events_with_frame_budget(orch, events)
            if processed < len(events):
                remainder = events[processed:]
                with orch._pending_lock:
                    orch._pending_events.extendleft(reversed(remainder))

            has_pending = False
            with orch._pending_lock:
                has_pending = bool(orch._pending_events)
                if has_pending:
                    orch._drain_scheduled = True

            _set_display_backpressure(orch, has_pending)

            _flush_and_refresh(
                orch,
                events,
                streaming_only,
                skip_sidebar=streaming_only or has_pending,
            )

            flush_commits = getattr(orch, 'flush_pending_final_commits', None)
            if callable(flush_commits):
                await flush_commits()

            if not has_pending:
                break

            elapsed = time.monotonic() - invocation_started
            if elapsed >= _TUI_DRAIN_INVOCATION_BUDGET_SECONDS:
                _force_immediate_drain(orch)
                break

            await asyncio.sleep(0)
    finally:
        orch._async_drain_active = False
        _set_display_backpressure(orch, False)

    elapsed_ms = (time.monotonic() - invocation_started) * 1000.0
    pending_depth = 0
    with orch._pending_lock:
        pending_depth = len(orch._pending_events)
        requested_while_active = (
            getattr(orch, '_drain_requested_while_active', False) is True
        )
        orch._drain_requested_while_active = False
    prep_depth = len(getattr(orch, '_render_prep_cache', {}) or {})
    _tui_logger.debug(
        'tui_drain_ms=%.1f tui_pending_depth=%d tui_prep_queue_depth=%d '
        'tui_last_batch=%d streaming_only=%s',
        elapsed_ms,
        pending_depth,
        prep_depth,
        len(last_batch),
        last_streaming_only,
    )
    if pending_depth and requested_while_active:
        _force_immediate_drain(orch)


async def wait_for_activity(
    orch: 'RendererEventProcessorMixin',
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


async def hydrate_recent_transcript(
    orch: 'RendererEventProcessorMixin',
    *,
    limit: int | None = None,
) -> int:
    """Render the most recent ledger events into an empty transcript."""
    from backend.cli.tui.constants import _TUI_RESUME_HYDRATE_EVENTS

    if limit is None:
        limit = _TUI_RESUME_HYDRATE_EVENTS
    event_stream = getattr(orch, '_event_stream', None)
    if event_stream is None or limit <= 0:
        return 0
    try:
        display = orch._tui._get_display()
    except Exception:
        return 0
    if getattr(orch._tui, '_welcome_visible', False):
        return 0
    get_welcome = getattr(orch._tui, '_get_welcome_widget', None)
    if callable(get_welcome) and get_welcome() is not None:
        return 0
    if getattr(display, 'child_widget_count', lambda: 0)() > 0:
        return 0
    try:
        events = list(event_stream.search_events(reverse=True, limit=limit))
    except Exception:
        return 0
    if not events:
        return 0
    events.reverse()
    orch._replay_mode = True
    try:
        idx = 0
        while idx < len(events):
            chunk = events[idx : idx + 25]
            processed = await _process_events_with_frame_budget(orch, chunk)
            idx += max(processed, 1)
            await asyncio.sleep(0)
    finally:
        orch._replay_mode = False
    sync = getattr(orch, '_sync_transcript_viewport', None)
    if callable(sync):
        sync()
    return len(events)


async def load_earlier_messages(
    orch: 'RendererEventProcessorMixin',
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
        events = list(
            event_stream.search_events(
                start_id=start_id,
                end_id=min_id,
                reverse=False,
            )
        )
    except Exception:
        return 0

    if not events:
        return 0

    orch._replay_mode = True
    orch._prepend_mode = True
    try:
        idx = 0
        while idx < len(events):
            chunk = events[idx : idx + 25]
            processed = await _process_events_with_frame_budget(orch, chunk)
            idx += max(processed, 1)
            await asyncio.sleep(0)
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


def _on_event(orch: 'RendererEventProcessorMixin', event: Any) -> None:
    # Deferred import: the test suite monkey-patches this constant on the
    # mixin module (``monkeypatch.setattr(_ep_mod, '_TUI_PENDING_EVENT_LIMIT', N)``).
    from backend.cli.tui.renderer.mixins.event_processor import (
        _TUI_PENDING_EVENT_LIMIT,
    )

    event_id = getattr(event, 'id', -1)
    should_schedule_drain = False
    with orch._pending_lock:
        if event_id >= 0:
            if (
                orch._min_rendered_event_id < 0
                or event_id < orch._min_rendered_event_id
            ):
                orch._min_rendered_event_id = event_id
            if event_id > orch._max_rendered_event_id:
                orch._max_rendered_event_id = event_id
        coalesced = _try_coalesce_streaming_enqueue(
            orch._pending_events, event
        ) or _try_coalesce_terminal_enqueue(orch._pending_events, event)
        if not coalesced:
            if _make_backpressure_room(
                orch,
                orch._pending_events,
                _TUI_PENDING_EVENT_LIMIT,
            ):
                should_schedule_drain = True
            orch._pending_events.append(event)
            if getattr(orch, '_pending_backpressure', False):
                should_schedule_drain = True
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


def _post_drain_message(orch: 'RendererEventProcessorMixin') -> None:
    orch._drain_debounce_handle = None
    try:
        orch._tui.post_message(RendererDrainRequested())
    except Exception:
        with orch._pending_lock:
            orch._drain_scheduled = False


def _signal_activity(
    orch: 'RendererEventProcessorMixin',
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
