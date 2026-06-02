"""Subscription methods for CLIEventRenderer.

Stream subscription & event dispatch (subscribe/reset/_on_event/drain/_process_event_data/handle_event).

Extracted from backend/cli/event_renderer.py to keep the parent module
under the per-file LOC budget. All methods rely on attributes/methods
defined on CLIEventRenderer; this mixin is meant to be combined with
that class via multiple inheritance.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import deque
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from rich import box
from rich.console import Console, ConsoleOptions, Group, RenderResult
from rich.live import Live
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.style import Style
from rich.text import Text

from backend.cli._event_renderer.constants import (
    THINK_EXTRACT_RE as _THINK_EXTRACT_RE,
)
from backend.cli._event_renderer.constants import (
    THINK_STRIP_RE as _THINK_STRIP_RE,
)
from backend.cli._event_renderer.error_panel import (
    build_error_panel as _build_error_panel,
)
from backend.cli._event_renderer.error_panel import (
    use_recoverable_notice_style as _use_recoverable_notice_style,
)
from backend.cli._event_renderer.panels import (
    PendingActivityCard,
)
from backend.cli._event_renderer.panels import (
    build_delegate_worker_panel as _build_delegate_worker_panel,
)
from backend.cli._event_renderer.panels import (
    build_system_notice_panel as _build_system_notice_panel,
)
from backend.cli._event_renderer.panels import (
    build_task_panel as _build_task_panel,
)
from backend.cli._event_renderer.panels import (
    delegate_worker_panel_signature as _delegate_worker_panel_signature,
)
from backend.cli._event_renderer.panels import (
    normalize_system_title as _normalize_system_title,
)
from backend.cli._event_renderer.panels import (
    task_panel_signature as _task_panel_signature,
)
from backend.cli._event_renderer.sidebar import (
    build_sidebar as _build_sidebar,
)
from backend.cli._event_renderer.sidebar import (
    compute_main_width as _compute_main_width,
)
from backend.cli._event_renderer.text_utils import (
    normalize_reasoning_text as _normalize_reasoning_text,
)
from backend.cli._event_renderer.text_utils import (
    sanitize_visible_transcript_text as _sanitize_visible_transcript_text,
)
from backend.cli._event_renderer.text_utils import (
    show_reasoning_text as _show_reasoning_text,
)
from backend.cli.hud import HUDBar
from backend.cli.layout_tokens import (
    ACTIVITY_BLOCK_BOTTOM_PAD,
    ACTIVITY_CARD_TITLE_SHELL,
    CALLOUT_PANEL_PADDING,
    LIVE_PANEL_ACCENT_STYLE,
    frame_live_body,
    frame_transcript_body,
    gap_below_live_section,
    spacer_live_section,
)
from backend.cli.path_links import file_uri_for_path, linkify_plain
from backend.cli.status_chrome import rich_fake_prompt_group, status_fields_from_hud
from backend.cli.theme import (
    CLR_ERR_BODY,
    CLR_ERR_ICON,
    CLR_STATUS_ERR,
    CLR_STATUS_WARN,
    CLR_USER_BG,
    CLR_USER_BORDER,
    CLR_WARN_BODY,
    CLR_WARN_ICON,
    STYLE_BOLD_DIM,
    STYLE_DIM,
    accessible_mode_enabled,
    get_grinta_pygments_style,
)
from backend.cli.tool_call_display import (
    looks_like_streaming_tool_arguments,
    streaming_args_hint,
    tool_headline,
    try_format_message_as_tool_json,
)
from backend.cli.transcript import (
    format_activity_block,
    format_activity_shell_block,
    format_activity_turn_header,
    format_ground_truth_tool_line,
)
from backend.core.enums import AgentState, EventSource
from backend.ledger import EventStreamSubscriber
from backend.ledger.action import (
    Action,
    NullAction,
    StreamingChunkAction,
)
from backend.ledger.observation import (
    AgentStateChangedObservation,
    NullObservation,
    Observation,
)

if TYPE_CHECKING:
    from backend.cli.event_renderer import CLIEventRenderer


logger = logging.getLogger(__name__)

from backend.cli.event_renderer import (  # noqa: F401, E402
    _SKIP_ACTIONS,
    _SKIP_OBSERVATIONS,
    _SUBSCRIBER,
)

class _EventRendererSubscriptionMixin(CLIEventRenderer if TYPE_CHECKING else object):
    """Mixin class — see module docstring."""

    async def handle_event(self, event: Any) -> None:
        self._process_event_data(event)
        self.refresh(force=True)
    def reset_subscription(self) -> None:
        if self._subscribed and self._subscribed_stream is not None:
            try:
                self._subscribed_stream.unsubscribe(_SUBSCRIBER, self)
            except Exception:
                pass
        self._subscribed = False
        self._subscribed_stream = None
    def subscribe(self, event_stream: EventStream, sid: str) -> None:
        if self._subscribed and self._subscribed_stream is event_stream:
            return
        if self._subscribed and self._subscribed_stream is not None:
            try:
                self._subscribed_stream.unsubscribe(_SUBSCRIBER, self)
            except Exception:
                pass
        event_stream.subscribe(_SUBSCRIBER, self._on_event_threadsafe, sid)
        self._subscribed = True
        self._subscribed_stream = event_stream
    def _on_event_threadsafe(self, event: Any) -> None:
        """Called from the EventStream's delivery thread pool.

        Appends the event to a thread-safe deque for later processing.
        NO terminal writes happen here — all rendering is done by
        ``drain_events()`` on the main thread.  This avoids two threads
        (delivery pool + Live auto-refresh timer) fighting over stdout.
        """
        self._pending_events.append(event)
        # Wake the main-thread waiter so it drains promptly.
        try:
            self._loop.call_soon_threadsafe(self._state_event.set)
        except RuntimeError:
            pass
    def drain_events(self) -> None:
        """Process all queued events and refresh.

        MUST be called from
        the main thread (the one that owns the Live display).

        Always refreshes even when no events were queued so that
        time-based widgets (e.g. the Thinking… timer) stay up to date.
        """
        while self._pending_events:
            event = self._pending_events.popleft()
            try:
                self._process_event_data(event)
            except Exception:
                logger.debug(
                    'Error processing event %s: %s',
                    type(event).__name__,
                    exc_info=True,
                )
        self.refresh(force=True)
    def _process_event_data(self, event: Any) -> None:
        """Update internal state for one event.  Does NOT call refresh()."""
        # Update HUD metrics first so token/cost/call counters advance even if
        # the event itself is later skipped from visual rendering.
        self._update_metrics(event)

        if isinstance(event, _SKIP_ACTIONS) or isinstance(event, _SKIP_OBSERVATIONS):
            return

        source = getattr(event, 'source', None)

        if isinstance(event, Action) and source == EventSource.AGENT:
            self._handle_agent_action(event)
            return

        if isinstance(event, Observation):
            self._handle_observation(event)
            return
