"""Event drain / activity machinery for :class:`RendererEventProcessorMixin`.

Owns:
- ``drain_events`` — atomic flush of the pending event queue into the
  transcript.
- ``wait_for_activity`` — async wait until either new events arrive or the
  timeout fires.
- ``_on_event`` — enqueue an event from any thread, coalescing progress above
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
from backend.cli.tui.renderer.handlers.task_tracking import (
    _is_task_tracking_event,
    eager_apply_task_tracking_event,
)
from backend.cli.tui.widgets.small import RendererDrainRequested

if TYPE_CHECKING:
    from backend.cli.tui.renderer.mixins.event_processor import (
        RendererEventProcessorMixin,
    )

_TUI_DRAIN_DEBOUNCE_SECONDS = 0.016

# Pending-queue depth at which we proactively disable transcript mount
# animations. Skipping the per-widget 0.2s animation during bursts prevents
# the Textual event loop from stalling while many cards mount at once.
_TUI_BACKPRESSURE_PENDING_THRESHOLD = 8


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


def _is_tool_step_preamble(event: Any) -> bool:
    """Return whether *event* must paint before the following tool card.

    A model response with both prose and a tool call becomes a transcript-only
    ``MessageAction`` followed by its executable action.  Keeping both in one
    drain pass makes Textual paint them together, leaving the last partial
    stream preview on screen until the tool card appears.  Yielding after the
    complete preamble gives the user one rendered frame with the full message.
    """
    from backend.ledger.action.message import MessageAction

    return bool(
        isinstance(event, MessageAction)
        and getattr(event, 'transcript_only', False)
        and str(getattr(event, 'content', '') or '').strip()
    )


def _streaming_channel_key(event: Any) -> tuple[str, str]:
    """Return the UI channel represented by a streaming snapshot.

    Assistant prose and streamed tool arguments both use
    ``StreamingChunkAction``.  They must never replace one another while the
    pending queue is coalesced: tool-argument snapshots are intentionally not
    rendered by the transcript, so allowing one to replace prose leaves the
    last visible sentence fragment frozen until the whole tool call ends.
    """
    if bool(getattr(event, 'is_tool_call', False)):
        return ('tool', str(getattr(event, 'tool_call_name', '') or ''))
    if str(getattr(event, 'tool_call_name', '') or '') == 'compaction':
        return ('compaction', '')
    return ('assistant', '')


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
            channel = _streaming_channel_key(event)
            end = idx + 1
            while (
                end < len(events)
                and isinstance(events[end], StreamingChunkAction)
                and not events[end - 1].is_final
                and _streaming_channel_key(events[end]) == channel
            ):
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
    if _streaming_channel_key(last) != _streaming_channel_key(event):
        return False
    if last.is_final:
        return False
    pending[-1] = event
    return True


def _coalesce_pending_backlog(pending: Any) -> int:
    """Merge adjacent stream snapshots with a linear pass over the deque.

    Terminal observations can carry output deltas and have distinct action
    causes. Replacing an earlier observation loses output and card completions.
    """
    original_length = len(pending)
    compacted = _collapse_streaming_chunks(list(pending))
    reclaimed = original_length - len(compacted)
    if reclaimed:
        pending.clear()
        pending.extend(compacted)
    return reclaimed


def _is_low_value_backlog_event(event: Any) -> bool:
    """Return True for events that are safe to skip under TUI pressure."""
    name = type(event).__name__
    if name == 'NullObservation':
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
    # The limit is a high-water mark for progress noise, not permission to
    # discard tool results, confirmations, or final assistant messages.
    return False


def _backpressure_scan_deferred(
    orch: 'RendererEventProcessorMixin', pending: Any, limit: int
) -> bool:
    if limit <= 0 or len(pending) < limit:
        return True
    next_scan = getattr(orch, '_next_backpressure_scan_depth', 0)
    return isinstance(next_scan, int) and len(pending) < next_scan


def _drop_pending_for_backpressure(pending: Any, limit: int) -> int:
    dropped = 0
    while len(pending) >= limit:
        if not _drop_one_pending_event_for_backpressure(pending):
            break
        dropped += 1
    return dropped


def _make_backpressure_room(
    orch: 'RendererEventProcessorMixin',
    pending: Any,
    limit: int,
) -> bool:
    """Bound disposable progress; retain milestones even above the soft limit."""
    if _backpressure_scan_deferred(orch, pending, limit):
        return False

    reclaimed = _coalesce_pending_backlog(pending)
    if reclaimed:
        orch._pending_backpressure_reclaimed = (
            getattr(orch, '_pending_backpressure_reclaimed', 0) + reclaimed
        )
        if len(pending) < limit:
            return True

    dropped = _drop_pending_for_backpressure(pending, limit)

    if dropped:
        orch._pending_events_dropped += dropped
        orch._pending_backpressure = True
    if len(pending) >= limit:
        # Avoid rescanning an all-milestone backlog on every arrival.
        orch._next_backpressure_scan_depth = len(pending) + 256
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


def _resume_after_tool_preamble_paint(
    orch: 'RendererEventProcessorMixin',
) -> None:
    """Resume event draining only after Textual paints the full preamble."""
    orch._tool_preamble_refresh_scheduled = False
    orch._tool_preamble_paint_pending = False
    with orch._pending_lock:
        has_pending = bool(orch._pending_events)
    if has_pending:
        _force_immediate_drain(orch)


def _schedule_resume_after_tool_preamble_paint(
    orch: 'RendererEventProcessorMixin',
) -> None:
    """Install one refresh barrier between assistant prose and its tool card."""
    if getattr(orch, '_tool_preamble_refresh_scheduled', False) is True:
        return
    orch._tool_preamble_refresh_scheduled = True
    call_after_refresh = getattr(orch._tui, 'call_after_refresh', None)
    if callable(call_after_refresh):
        try:
            call_after_refresh(partial(_resume_after_tool_preamble_paint, orch))
            return
        except Exception:
            pass
    _resume_after_tool_preamble_paint(orch)


def drain_events(orch: 'RendererEventProcessorMixin') -> None:
    """Synchronous drain for non-async contexts (backward compatibility)."""
    with orch._pending_lock:
        events = list(orch._pending_events)
        orch._pending_events.clear()
        orch._drain_scheduled = False
        dropped = orch._pending_events_dropped
        orch._pending_events_dropped = 0
        orch._pending_backpressure = False
        orch._next_backpressure_scan_depth = 0
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
        orch._next_backpressure_scan_depth = 0
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

    append_history = getattr(orch, '_append_history_items', None)
    if callable(append_history):
        append_history(notice, Text(''))
        return

    orch._history.append(notice)
    orch._history.append(Text(''))


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


async def _preprocess_streaming_chunk_async(
    orch: 'RendererEventProcessorMixin', event: Any
) -> None:
    if getattr(event, 'is_tool_call', False):
        return
    normalize = getattr(orch, '_normalize_final_response_text', None)
    raw = getattr(event, 'accumulated', '') or ''
    text = normalize(raw) if callable(normalize) else raw
    if text.strip():
        from backend.cli.tui.renderer.prep import prep_streaming_response_async

        await prep_streaming_response_async(orch, text)


async def _preprocess_file_edit_event_async(
    orch: 'RendererEventProcessorMixin', event: Any
) -> None:
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
        bound = getattr(orch, '_bound_event_id_cache', None)
        if callable(bound):
            bound(cache)


async def _preprocess_event_async(
    orch: 'RendererEventProcessorMixin', event: Any
) -> None:
    """Run heavy prep off the UI thread before synchronous dispatch."""
    from backend.ledger.action.message import StreamingChunkAction

    # Streaming-response markdown/syntax highlighting is CPU-heavy; prepare it
    # off-thread so _apply_live_response_render can reuse the result instead of
    # running Pygments/Markdown on the Textual event loop.
    if isinstance(event, StreamingChunkAction):
        await _preprocess_streaming_chunk_async(orch, event)
        return
    await _preprocess_file_edit_event_async(orch, event)


async def _process_events_with_frame_budget(
    orch: 'RendererEventProcessorMixin',
    events: list[Any],
) -> int:
    """Process events until the frame budget elapses. Returns count processed."""
    started = time.monotonic()
    processed = 0
    generation = getattr(orch, '_render_generation', 0)
    for event in events:
        event_started = time.monotonic()
        await _preprocess_event_async(orch, event)
        if generation != getattr(orch, '_render_generation', 0):
            # Clear Transcript ran while preparation was in flight. Consume
            # this old batch without resurrecting its content on the screen.
            return len(events)
        prepared_at = time.monotonic()
        orch._process_event(event)
        event_finished = time.monotonic()
        if event_finished - event_started >= 0.05:
            _tui_logger.debug(
                'tui_slow_event=%s prep_ms=%.1f dispatch_ms=%.1f',
                type(event).__name__,
                (prepared_at - event_started) * 1000,
                (event_finished - prepared_at) * 1000,
            )
        processed += 1
        if _is_tool_step_preamble(event):
            # The caller requeues the remaining events and returns to the
            # Textual loop, allowing the complete preamble to paint before
            # its next tool card is mounted.
            orch._tool_preamble_paint_pending = True
            break
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


def _requeue_unprocessed_events(
    orch: 'RendererEventProcessorMixin',
    events: list[Any],
    processed: int,
) -> None:
    if processed < len(events):
        remainder = events[processed:]
        with orch._pending_lock:
            orch._pending_events.extendleft(reversed(remainder))


def _mark_pending_drain_scheduled(
    orch: 'RendererEventProcessorMixin',
) -> bool:
    with orch._pending_lock:
        has_pending = bool(orch._pending_events)
        if has_pending:
            orch._drain_scheduled = True
    return has_pending


async def _flush_pending_final_commits_async(
    orch: 'RendererEventProcessorMixin',
) -> None:
    flush_commits = getattr(orch, 'flush_pending_final_commits', None)
    if callable(flush_commits):
        await flush_commits()


def _pause_for_tool_preamble_paint(
    orch: 'RendererEventProcessorMixin',
) -> bool:
    if getattr(orch, '_tool_preamble_paint_pending', False) is not True:
        return False
    # ``call_after_refresh`` is the actual paint boundary.  A bare event-loop
    # yield is insufficient because Textual can process another drain message
    # before composing the next frame.
    _schedule_resume_after_tool_preamble_paint(orch)
    return True


def _reset_drain_activity_state(
    orch: 'RendererEventProcessorMixin',
) -> tuple[bool, int]:
    with orch._pending_lock:
        orch._drain_requested_while_active = False
        has_pending = bool(orch._pending_events)
        pending_depth = len(orch._pending_events)
    return has_pending, pending_depth


def _finish_drain_pass(
    orch: 'RendererEventProcessorMixin',
    invocation_started: float,
    last_batch: list[Any],
    last_streaming_only: bool,
) -> None:
    has_pending, pending_depth = _reset_drain_activity_state(orch)
    _set_display_backpressure(orch, has_pending)
    _tui_logger.debug(
        'tui_drain_ms=%.1f tui_pending_depth=%d tui_last_batch=%d streaming_only=%s',
        (time.monotonic() - invocation_started) * 1000,
        pending_depth,
        len(last_batch),
        last_streaming_only,
    )
    if not has_pending:
        return
    if getattr(orch, '_tool_preamble_paint_pending', False) is True:
        _schedule_resume_after_tool_preamble_paint(orch)
    else:
        _force_immediate_drain(orch)


async def drain_events_async(orch: 'RendererEventProcessorMixin') -> None:
    """Async drain that yields control to the event loop periodically.

    Processes multiple micro-batches per invocation up to a wall-clock cap so
    backlog drains faster without monopolizing the Textual event loop.
    """
    if getattr(orch, '_tool_preamble_paint_pending', False) is True:
        _schedule_resume_after_tool_preamble_paint(orch)
        return
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
            _requeue_unprocessed_events(orch, events, processed)

            has_pending = _mark_pending_drain_scheduled(orch)

            _set_display_backpressure(orch, has_pending)

            _flush_and_refresh(
                orch,
                events,
                streaming_only,
                skip_sidebar=streaming_only or has_pending,
            )

            await _flush_pending_final_commits_async(orch)

            if _pause_for_tool_preamble_paint(orch):
                break

            if not has_pending:
                break

            if (
                time.monotonic() - invocation_started
                >= _TUI_DRAIN_INVOCATION_BUDGET_SECONDS
            ):
                break

            await asyncio.sleep(0)
    finally:
        orch._async_drain_active = False
        _finish_drain_pass(
            orch,
            invocation_started,
            last_batch,
            last_streaming_only,
        )


async def wait_for_activity(
    orch: 'RendererEventProcessorMixin',
    wait_timeout_sec: float = 0.5,
) -> Any:
    with orch._pending_lock:
        has_pending = bool(orch._pending_events)
    if has_pending:
        await orch.drain_events_async()
        orch._state_event.clear()
        return orch._current_state
    try:
        await asyncio.wait_for(orch._state_event.wait(), timeout=wait_timeout_sec)
    except TimeoutError:
        return None
    finally:
        orch._state_event.clear()
    await orch.drain_events_async()
    return orch._current_state


_LOAD_EARLIER_BATCH_SIZE = 100


def _hydration_event_stream(
    orch: 'RendererEventProcessorMixin',
    limit: int,
) -> Any | None:
    event_stream = getattr(orch, '_event_stream', None)
    if event_stream is None or limit <= 0:
        return None
    try:
        display = orch._tui._get_display()
    except Exception:
        return None
    if getattr(orch._tui, '_welcome_visible', False):
        return None
    get_welcome = getattr(orch._tui, '_get_welcome_widget', None)
    if callable(get_welcome) and get_welcome() is not None:
        return None
    count = getattr(display, 'child_widget_count', 0)
    if (count() if callable(count) else count) > 0:
        return None
    return event_stream


async def _replay_event_chunks(
    orch: 'RendererEventProcessorMixin',
    events: list[Any],
    generation: int,
) -> bool:
    idx = 0
    while idx < len(events):
        if generation != getattr(orch, '_render_generation', 0):
            return False
        chunk = events[idx : idx + 25]
        processed = await _process_events_with_frame_budget(orch, chunk)
        idx += max(processed, 1)
        await asyncio.sleep(0)
    return generation == getattr(orch, '_render_generation', 0)


async def hydrate_recent_transcript(
    orch: 'RendererEventProcessorMixin',
    *,
    limit: int | None = None,
) -> int:
    """Render the most recent ledger events into an empty transcript."""
    from backend.cli.tui.constants import _TUI_RESUME_HYDRATE_EVENTS

    if limit is None:
        limit = _TUI_RESUME_HYDRATE_EVENTS
    event_stream = _hydration_event_stream(orch, limit)
    if event_stream is None:
        return 0
    generation = getattr(orch, '_render_generation', 0)
    try:
        events = await asyncio.to_thread(
            lambda: list(event_stream.search_events(reverse=True, limit=limit))
        )
    except Exception:
        return 0
    if not events or generation != getattr(orch, '_render_generation', 0):
        return 0
    events.reverse()
    orch._replay_mode = True
    try:
        if not await _replay_event_chunks(orch, events, generation):
            return 0
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
    generation = getattr(orch, '_render_generation', 0)
    try:
        events = await asyncio.to_thread(
            lambda: list(
                event_stream.search_events(
                    start_id=start_id,
                    end_id=min_id,
                    reverse=False,
                )
            )
        )
    except Exception:
        return 0

    if not events or generation != getattr(orch, '_render_generation', 0):
        return 0

    orch._replay_mode = True
    orch._prepend_mode = True
    try:
        if not await _replay_event_chunks(orch, events, generation):
            return 0
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


def _update_event_id_bounds(orch: 'RendererEventProcessorMixin', event_id: int) -> None:
    if orch._min_rendered_event_id < 0 or event_id < orch._min_rendered_event_id:
        orch._min_rendered_event_id = event_id
    orch._max_rendered_event_id = max(orch._max_rendered_event_id, event_id)


def _enqueue_pending_event(
    orch: 'RendererEventProcessorMixin',
    event: Any,
    *,
    priority_event: bool,
    limit: int,
) -> tuple[bool, bool]:
    coalesced = _try_coalesce_streaming_enqueue(orch._pending_events, event)
    should_schedule_drain = False
    if not coalesced:
        if _make_backpressure_room(orch, orch._pending_events, limit):
            should_schedule_drain = True
        if priority_event:
            orch._pending_events.appendleft(event)
        else:
            orch._pending_events.append(event)
        if getattr(orch, '_pending_backpressure', False):
            should_schedule_drain = True
        if not orch._drain_scheduled:
            orch._drain_scheduled = True
            should_schedule_drain = True
    elif not orch._drain_scheduled and not getattr(orch, '_async_drain_active', False):
        orch._drain_scheduled = True
        should_schedule_drain = True
    return coalesced, should_schedule_drain


def _request_display_backpressure(
    orch: 'RendererEventProcessorMixin',
) -> None:
    try:
        orch._loop.call_soon_threadsafe(
            partial(_set_display_backpressure, orch, True),
        )
    except RuntimeError:
        pass


def _schedule_activity_signal(
    orch: 'RendererEventProcessorMixin',
    should_schedule_drain: bool,
) -> None:
    try:
        orch._loop.call_soon_threadsafe(
            partial(_signal_activity, orch),
            should_schedule_drain,
        )
    except RuntimeError:
        pass


def _on_event(orch: 'RendererEventProcessorMixin', event: Any) -> None:
    # Deferred import: the test suite monkey-patches this constant on the
    # mixin module (``monkeypatch.setattr(_ep_mod, '_TUI_PENDING_EVENT_LIMIT', N)``).
    from backend.cli.tui.renderer.mixins.event_processor import (
        _TUI_PENDING_EVENT_LIMIT,
    )

    event_id = getattr(event, 'id', -1)
    priority_event = _is_task_tracking_event(event)
    with orch._pending_lock:
        if event_id >= 0:
            _update_event_id_bounds(orch, event_id)
        coalesced, should_schedule_drain = _enqueue_pending_event(
            orch,
            event,
            priority_event=priority_event,
            limit=_TUI_PENDING_EVENT_LIMIT,
        )
        # Predictive backpressure: flag the display as soon as the queue starts
        # backing up so the very first burst card mounts without animation,
        # rather than waiting for a drain pass to observe leftover events.
        pending_backpressure = (
            len(orch._pending_events) > _TUI_BACKPRESSURE_PENDING_THRESHOLD
        )
    if priority_event:
        eager_apply_task_tracking_event(orch, event)
    skip_signal = coalesced and (
        getattr(orch, '_drain_scheduled', False)
        or getattr(orch, '_async_drain_active', False)
    )
    if skip_signal:
        if pending_backpressure:
            _request_display_backpressure(orch)
        return
    _schedule_activity_signal(orch, should_schedule_drain)
    # _on_event runs on a background thread; never touch Textual widgets here.
    # Hop onto the event loop to toggle display backpressure.
    if pending_backpressure:
        _request_display_backpressure(orch)


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
    if getattr(orch, '_tool_preamble_paint_pending', False) is True:
        _schedule_resume_after_tool_preamble_paint(orch)
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
