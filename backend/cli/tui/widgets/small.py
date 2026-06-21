"""Small widget classes extracted from backend.cli.tui.app.

Pure code motion: class bodies are byte-identical to the
pre-split version. Kept in a single module because each class
is <3 KB and they share similar import profiles.
"""

from __future__ import annotations

import json
import time
from typing import Any

import pyperclip
from pathlib import Path
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Label, Select, Static, TextArea

from backend.core.interaction_modes import AGENT_MODE, VISIBLE_INTERACTION_MODES
from backend.cli.tui.transcript_typography import esc_hint_markup

_DEBUG_SESSION_ID = '64043f'
_DEBUG_LOG_PATH = Path(__file__).resolve().parents[4] / 'debug-64043f.log'


def _agent_debug_log(
    *,
    run_id: str,
    hypothesis_id: str,
    location: str,
    message: str,
    data: dict[str, Any],
) -> None:
    payload = {
        'sessionId': _DEBUG_SESSION_ID,
        'id': f'{_DEBUG_SESSION_ID}-{time.time_ns()}',
        'runId': run_id,
        'hypothesisId': hypothesis_id,
        'location': location,
        'message': message,
        'data': data,
        'timestamp': int(time.time() * 1000),
    }
    line = json.dumps(payload, ensure_ascii=True, default=str) + '\n'
    targets: list[Path] = [_DEBUG_LOG_PATH]
    try:
        from backend.core.logging.logger import get_log_dir

        session_log_path = Path(get_log_dir()) / f'debug-{_DEBUG_SESSION_ID}.log'
        if session_log_path not in targets:
            targets.append(session_log_path)
    except Exception:
        pass
    for path in targets:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('a', encoding='utf-8') as handle:
                handle.write(line)
        except Exception:
            continue


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
        self._debug_mount_logged = False
        self._follow_tail_pending = False

    def compose(self) -> ComposeResult:
        yield ScrollTailBadge()

    def on_mount(self) -> None:
        self._scroll_badge = self.query_one('#scroll-badge', ScrollTailBadge)
        if not self._debug_mount_logged:
            self._debug_mount_logged = True
            #region agent log
            _agent_debug_log(
                run_id='pre-fix',
                hypothesis_id='H4',
                location='widgets/small.py:on_mount',
                message='transcript instrumentation active',
                data={'widget': 'Transcript'},
            )
            #endregion

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

    def _set_user_scrolled_away(
        self, value: bool, *, reason: str = 'unspecified'
    ) -> None:
        was_away = bool(self._user_scrolled_away)
        was_user_initiated = bool(self._user_initiated_scroll_away)
        self._user_scrolled_away = value
        if not value:
            self._user_initiated_scroll_away = False
            self._tail_unread_count = 0
        if was_away != bool(value):
            #region agent log
            _agent_debug_log(
                run_id='pre-fix',
                hypothesis_id='H6',
                location='widgets/small.py:_set_user_scrolled_away',
                message='user scrolled-away state changed',
                data={
                    'reason': reason,
                    'from': bool(was_away),
                    'to': bool(value),
                    'wasUserInitiatedAway': bool(was_user_initiated),
                    'isUserInitiatedAway': bool(self._user_initiated_scroll_away),
                    'scrollY': round(float(self.scroll_y), 2),
                    'maxScrollY': round(float(self.max_scroll_y), 2),
                },
            )
            #endregion
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
        self.force_scroll_end(reason='tail_badge_follow')

    def _sync_scroll_state_from_position(
        self, *, from_user_scroll: bool = False
    ) -> None:
        """Update follow-tail state from scroll position.

        Content growth increases max_scroll_y while scroll_y stays put; that
        must not be treated as the user leaving the tail. Only upward movement
        (or already being away from the bottom without fresh content) counts.

        Re-engaging follow (clearing ``_user_scrolled_away``) is gated behind
        ``from_user_scroll``: only a genuine user gesture that lands at the
        bottom may resume auto-follow. Programmatic re-pins (follow-tail /
        force_scroll_end) reach this method via ``on_scroll`` once
        ``_suppress_scroll_sync`` is cleared; treating those bottom landings as
        "user returned to tail" wipes a deliberate scroll-away and snaps the
        viewport back to the tail, which is the scroll-freeze symptom.
        """
        max_y = self.max_scroll_y
        scroll_y = self.scroll_y
        last_max_y = self._last_max_scroll_y
        last_scroll_y = self._last_scroll_y
        self._last_max_scroll_y = max_y
        self._last_scroll_y = scroll_y

        if self._user_scrolled_away:
            if from_user_scroll and self._was_at_bottom():
                #region agent log
                _agent_debug_log(
                    run_id='post-fix',
                    hypothesis_id='H6',
                    location='widgets/small.py:_sync_scroll_state_from_position',
                    message='user scrolled back to bottom; re-engaging follow',
                    data={
                        'scrollY': round(float(scroll_y), 2),
                        'lastScrollY': round(float(last_scroll_y), 2),
                        'maxScrollY': round(float(max_y), 2),
                        'userInitiatedAway': bool(self._user_initiated_scroll_away),
                    },
                )
                #endregion
                self._set_user_scrolled_away(
                    False,
                    reason='user_scrolled_back_to_bottom',
                )
            elif self._was_at_bottom() and scroll_y > last_scroll_y + 0.5:
                #region agent log
                _agent_debug_log(
                    run_id='post-fix',
                    hypothesis_id='H6',
                    location='widgets/small.py:_sync_scroll_state_from_position',
                    message='programmatic bottom landing ignored (away preserved)',
                    data={
                        'scrollY': round(float(scroll_y), 2),
                        'lastScrollY': round(float(last_scroll_y), 2),
                        'maxScrollY': round(float(max_y), 2),
                        'userInitiatedAway': bool(self._user_initiated_scroll_away),
                    },
                )
                #endregion
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
            self._set_user_scrolled_away(True, reason='pause_auto_scroll')
            #region agent log
            _agent_debug_log(
                run_id='pre-fix',
                hypothesis_id='H4',
                location='widgets/small.py:pause_auto_scroll',
                message='user paused auto-scroll',
                data={
                    'scrollY': round(float(self.scroll_y), 2),
                    'maxScrollY': round(float(self.max_scroll_y), 2),
                    'tailUnread': int(self._tail_unread_count),
                },
            )
            #endregion

    def _content_widgets(self) -> list[Widget]:
        widgets: list[Widget] = []
        for child in self.children:
            if child is self._scroll_badge:
                continue
            if child is self._load_earlier_button:
                continue
            if getattr(child, '_tui_removing', False):
                continue
            widgets.append(child)
        return widgets

    def sync_viewport(self, renderer: Any) -> None:
        """Unmount off-viewport widgets while retaining render cache for replay."""
        from backend.cli.tui.constants import (
            _TUI_VIEWPORT_MAX_MOUNTED,
            _TUI_VIEWPORT_OVERSCAN,
        )
        from backend.cli.tui.renderer.prep import RenderArtifact

        widgets = self._content_widgets()
        max_mounted = _TUI_VIEWPORT_MAX_MOUNTED
        if len(widgets) <= max_mounted:
            return

        overflow = len(widgets) - max_mounted

        if not self.should_follow_tail():
            # Bound mounted-widget growth even while the user is scrolled away.
            # New content keeps mounting at the tail; skipping pruning here lets
            # the mounted set grow without limit (the confirmed freeze cause).
            # Prune the oldest widgets sitting fully ABOVE the viewport, then
            # re-anchor the scroll so the visible content does not jump. Pruned
            # top widgets are replayable via the existing load-earlier path.
            self._prune_above_viewport(
                renderer,
                overflow,
                overscan=_TUI_VIEWPORT_OVERSCAN,
                max_mounted=max_mounted,
            )
            return

        to_unmount = widgets[:overflow]
        #region agent log
        _agent_debug_log(
            run_id='pre-fix',
            hypothesis_id='H1',
            location='widgets/small.py:sync_viewport',
            message='viewport pruning mounted widgets',
            data={
                'widgetCount': len(widgets),
                'maxMounted': max_mounted,
                'overflow': overflow,
                'unmountCount': len(to_unmount),
                'underBackpressure': bool(self._under_backpressure),
            },
        )
        #endregion

        cache = getattr(renderer, '_render_cache', None)
        for widget in to_unmount:
            setattr(widget, '_tui_removing', True)
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

    def _prune_above_viewport(
        self,
        renderer: Any,
        overflow: int,
        *,
        overscan: int,
        max_mounted: int,
    ) -> None:
        """Prune oldest widgets fully above the viewport while scrolled away.

        Keeps an ``overscan`` margin of widgets above the viewport for smooth
        upward scrolling, caches removed widgets for replay, and re-anchors the
        scroll position so the user's visible content does not shift.
        """
        from backend.cli.tui.renderer.prep import RenderArtifact

        scroll_y = float(self.scroll_y)
        widgets = self._content_widgets()

        # Locate the first widget intersecting (or below) the viewport top.
        anchor_index: int | None = None
        for idx, widget in enumerate(widgets):
            region = getattr(widget, 'virtual_region', None)
            if region is None:
                return
            if float(region.y) + float(region.height) > scroll_y:
                anchor_index = idx
                break
        if anchor_index is None:
            return

        prunable_end = max(0, anchor_index - max(0, overscan))
        prunable = widgets[:prunable_end][:overflow]
        if not prunable:
            #region agent log
            _agent_debug_log(
                run_id='post-fix',
                hypothesis_id='H1',
                location='widgets/small.py:_prune_above_viewport',
                message='away prune skipped: no off-screen room above viewport',
                data={
                    'widgetCount': len(widgets),
                    'maxMounted': max_mounted,
                    'overflow': overflow,
                    'anchorIndex': anchor_index,
                    'scrollY': round(scroll_y, 2),
                },
            )
            #endregion
            return

        anchor = widgets[anchor_index]
        anchor_region = getattr(anchor, 'virtual_region', None)
        anchor_offset = (
            float(anchor_region.y) - scroll_y if anchor_region is not None else 0.0
        )

        cache = getattr(renderer, '_render_cache', None)
        removed = 0
        for widget in prunable:
            setattr(widget, '_tui_removing', True)
            event_id = getattr(widget, '_ledger_event_id', None)
            if cache is not None and event_id is not None:
                size = getattr(widget, 'size', None)
                cache[event_id] = RenderArtifact(
                    event_id,
                    widget,
                    measured_height=max(size.height, 1) if size else 1,
                )
            try:
                widget.remove()
                removed += 1
            except Exception:
                pass

        if not removed:
            return

        #region agent log
        _agent_debug_log(
            run_id='post-fix',
            hypothesis_id='H1',
            location='widgets/small.py:_prune_above_viewport',
            message='viewport pruned above-viewport widgets while away from tail',
            data={
                'widgetCountBefore': len(widgets),
                'removed': removed,
                'widgetCountAfter': len(widgets) - removed,
                'maxMounted': max_mounted,
                'anchorIndex': anchor_index,
                'scrollY': round(scroll_y, 2),
            },
        )
        #endregion

        # Re-anchor after the removal relayout so the visible content stays put.
        self._suppress_scroll_sync = True

        def _reanchor() -> None:
            try:
                region = getattr(anchor, 'virtual_region', None)
                if region is not None:
                    new_y = max(0.0, float(region.y) - anchor_offset)
                    self.scroll_to(y=new_y, animate=False, immediate=True)
            except Exception:
                pass
            finally:
                self.call_after_refresh(self._release_programmatic_scroll)

        self.call_after_refresh(_reanchor)

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
            #region agent log
            _agent_debug_log(
                run_id='pre-fix',
                hypothesis_id='H2',
                location='widgets/small.py:on_scroll',
                message='scroll event ignored due suppress flag',
                data={
                    'suppressScrollSync': True,
                    'scrollY': round(float(self.scroll_y), 2),
                    'maxScrollY': round(float(self.max_scroll_y), 2),
                    'userScrolledAway': bool(self._user_scrolled_away),
                },
            )
            #endregion
            return
        self._sync_scroll_state_from_position()
        self._maybe_prefetch_earlier()

    def _on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        # Register the user scroll-away before delegating, and bypass the
        # programmatic-scroll guard so an in-flight follow-tail cannot
        # swallow this input during active streaming.
        self._suppress_scroll_sync = False
        self.pause_auto_scroll()
        #region agent log
        _agent_debug_log(
            run_id='pre-fix',
            hypothesis_id='H4',
            location='widgets/small.py:_on_mouse_scroll_up',
            message='mouse scroll up received by transcript',
            data={
                'scrollYBefore': round(float(self.scroll_y), 2),
                'maxScrollYBefore': round(float(self.max_scroll_y), 2),
                'userScrolledAway': bool(self._user_scrolled_away),
            },
        )
        #endregion
        super()._on_mouse_scroll_up(event)

    def _sync_scroll_state_from_user_scroll(self) -> None:
        self._sync_scroll_state_from_position(from_user_scroll=True)

    def _on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        super()._on_mouse_scroll_down(event)
        self.call_after_refresh(self._sync_scroll_state_from_user_scroll)

    def user_scroll_page_up(self, *, animate: bool = True) -> None:
        self._suppress_scroll_sync = False
        self.pause_auto_scroll()
        self.scroll_page_up(animate=animate)

    def user_scroll_page_down(self, *, animate: bool = True) -> None:
        self.scroll_page_down(
            animate=animate,
            on_complete=self._sync_scroll_state_from_user_scroll,
        )
        self.call_after_refresh(self._sync_scroll_state_from_user_scroll)

    def user_scroll_home(self, *, animate: bool = True) -> None:
        self._suppress_scroll_sync = False
        self.pause_auto_scroll()
        self.scroll_home(
            animate=animate,
            on_complete=self._sync_scroll_state_from_user_scroll,
        )

    def user_scroll_end(self, *, animate: bool = False) -> None:
        self.force_scroll_end(animate=animate, reason='user_scroll_end')

    def follow_tail(self) -> None:
        """Pin the transcript to the latest content when the user is following."""
        if self._user_scrolled_away:
            return
        self._schedule_follow_tail()

    def _schedule_follow_tail(self) -> None:
        """Scroll after layout refresh so max_scroll_y reflects new children."""
        if self._follow_tail_pending:
            return
        self._follow_tail_pending = True

        def _scroll_after_layout() -> None:
            try:
                if self._user_scrolled_away:
                    return
                was_suppressed = bool(self._suppress_scroll_sync)
                self._suppress_scroll_sync = True
                if was_suppressed:
                    #region agent log
                    _agent_debug_log(
                        run_id='pre-fix',
                        hypothesis_id='H5',
                        location='widgets/small.py:_schedule_follow_tail',
                        message='follow-tail scheduled while suppress already active',
                        data={
                            'scrollY': round(float(self.scroll_y), 2),
                            'maxScrollY': round(float(self.max_scroll_y), 2),
                            'underBackpressure': bool(self._under_backpressure),
                        },
                    )
                    #endregion
                self.scroll_end(animate=False, force=True, immediate=True)
                self.call_after_refresh(self._release_programmatic_scroll)
            finally:
                self._follow_tail_pending = False

        self.call_after_refresh(_scroll_after_layout)

    def _release_programmatic_scroll(self) -> None:
        self._suppress_scroll_sync = False
        self._sync_scroll_state_from_position()
        #region agent log
        _agent_debug_log(
            run_id='pre-fix',
            hypothesis_id='H2',
            location='widgets/small.py:_release_programmatic_scroll',
            message='programmatic scroll suppression released',
            data={
                'scrollY': round(float(self.scroll_y), 2),
                'maxScrollY': round(float(self.max_scroll_y), 2),
                'userInitiatedAway': bool(self._user_initiated_scroll_away),
                'userScrolledAway': bool(self._user_scrolled_away),
            },
        )
        #endregion
        if self._was_at_bottom() and not self._user_initiated_scroll_away:
            self._set_user_scrolled_away(
                False, reason='release_programmatic_bottom'
            )

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
        content_count = self.child_widget_count
        if content_count and content_count % 200 == 0:
            #region agent log
            _agent_debug_log(
                run_id='pre-fix',
                hypothesis_id='H1',
                location='widgets/small.py:append_widget',
                message='transcript content growth checkpoint',
                data={
                    'contentCount': content_count,
                    'shouldFollow': bool(should_follow),
                    'userScrolledAway': bool(self._user_scrolled_away),
                    'underBackpressure': bool(self._under_backpressure),
                    'tailUnread': int(self._tail_unread_count),
                    'scrollY': round(float(self.scroll_y), 2),
                    'maxScrollY': round(float(self.max_scroll_y), 2),
                },
            )
            #endregion

    def write(self, renderable: Any) -> None:
        """Compatibility method for RichLog interface."""
        self.append_widget(Static(renderable))

    def force_scroll_end(
        self, *, animate: bool = False, reason: str = 'force_scroll_end'
    ) -> None:
        """Scroll to bottom regardless of user scroll state."""
        #region agent log
        _agent_debug_log(
            run_id='pre-fix',
            hypothesis_id='H7',
            location='widgets/small.py:force_scroll_end',
            message='force_scroll_end invoked',
            data={
                'reason': reason,
                'scrollY': round(float(self.scroll_y), 2),
                'maxScrollY': round(float(self.max_scroll_y), 2),
                'userInitiatedAway': bool(self._user_initiated_scroll_away),
                'userScrolledAway': bool(self._user_scrolled_away),
            },
        )
        #endregion
        self._set_user_scrolled_away(False, reason=f'force_scroll_end:{reason}')
        self._suppress_scroll_sync = True
        self.scroll_end(animate=animate, force=True, immediate=not animate)
        self.call_after_refresh(self._release_programmatic_scroll)

    def clear(self) -> None:
        """Compatibility method for RichLog interface."""
        self.remove_children()
        self._scroll_badge = None
        self._user_scrolled_away = False
        self._user_initiated_scroll_away = False
        self._follow_tail_pending = False
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
            if getattr(child, '_tui_removing', False):
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
            if getattr(child, '_tui_removing', False):
                continue
            try:
                setattr(child, '_tui_removing', True)
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

    def _resolve_grinta_screen(self) -> Any | None:
        """Return the main Grinta screen even when a modal/detail is stacked."""
        app = getattr(self, 'app', None)
        if app is not None:
            main = getattr(app, '_screen', None)
            if main is not None and hasattr(main, 'try_paste_clipboard_image'):
                return main
            screen = getattr(app, 'screen', None)
            if screen is not None and hasattr(screen, 'try_paste_clipboard_image'):
                return screen
        return getattr(self, 'screen', None)

    def _paste_target_screen(self) -> Any | None:
        return self._resolve_grinta_screen()

    def _try_remove_pending_image_attachment(self) -> bool:
        """Remove staged images when the input is empty (backspace/delete)."""
        screen = self._paste_target_screen()
        if screen is None or self.text.strip():
            return False
        remove_last = getattr(screen, 'remove_last_pending_image_attachment', None)
        if callable(remove_last) and remove_last():
            return True
        return False

    def _try_clear_pending_image_attachments_on_empty_text(
        self, previous: str, text: str
    ) -> None:
        """Clear staged images when the user deletes all typed text."""
        if not previous.strip() or text.strip():
            return
        screen = self._paste_target_screen()
        if screen is None:
            return
        clear_all = getattr(screen, 'clear_pending_image_attachments', None)
        if callable(clear_all):
            clear_all()

    async def _try_attach_clipboard_image(self) -> bool:
        """Attach a clipboard image or report why paste could not continue."""
        screen = self._paste_target_screen()
        if screen is None or not hasattr(screen, 'try_paste_clipboard_image'):
            return False
        if await screen.try_paste_clipboard_image():
            return True
        from backend.cli.tui.image_attachments import clipboard_likely_has_image

        if clipboard_likely_has_image():
            notify = getattr(screen, 'notify_warning', None)
            if callable(notify):
                notify(
                    'Clipboard contains an image but Grinta could not read it. '
                    'Try copying again or use the attach-images action.'
                )
            return True
        return False

    def watch_text(self, text: str) -> None:
        previous = self._previous_input_text
        self._previous_input_text = text
        self._try_clear_pending_image_attachments_on_empty_text(previous, text)
        screen = self._paste_target_screen()
        if screen is None:
            return
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
        if await self._try_attach_clipboard_image():
            event.prevent_default()
            event.stop()
            return
        event.prevent_default()
        self._paste_text_from_clipboard(event)

    async def action_paste(self) -> None:
        """Paste from system clipboard directly."""
        if self.read_only:
            return
        if await self._try_attach_clipboard_image():
            return
        try:
            pyperclip.paste()
        except Exception:
            return super().action_paste()
        self._paste_text_from_clipboard()

    def on_key(self, event: events.Key) -> None:
        if event.key in {'backspace', 'delete'} and self._try_remove_pending_image_attachment():
            event.prevent_default()
            event.stop()
            return
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
            yield Label(
                esc_hint_markup('Interrupt'),
                id='hud-hint-interrupt',
            )
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
