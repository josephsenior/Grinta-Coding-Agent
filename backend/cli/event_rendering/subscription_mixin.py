"""Subscription methods for CLIEventRenderer.

Stream subscription & event dispatch (subscribe/reset/_on_event/drain/_process_event_data/handle_event).

Extracted from backend/cli/event_renderer.py to keep the parent module
under the per-file LOC budget. All methods rely on attributes/methods
defined on CLIEventRenderer; this mixin is meant to be combined with
that class via multiple inheritance.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from backend.core.enums import EventSource
from backend.ledger import EventStream
from backend.ledger.action import (
    Action,
)
from backend.ledger.observation import (
    Observation,
)

if TYPE_CHECKING:
    from backend.cli.event_renderer import CLIEventRenderer


logger = logging.getLogger(__name__)

from backend.cli.event_rendering.renderer_constants import (  # noqa: E402, I001
    SKIP_ACTIONS as _SKIP_ACTIONS,
)
from backend.cli.event_rendering.renderer_constants import (  # noqa: E402
    SKIP_OBSERVATIONS as _SKIP_OBSERVATIONS,
)
from backend.cli.event_rendering.renderer_constants import SUBSCRIBER as _SUBSCRIBER  # noqa: E402


class SubscriptionMixin(CLIEventRenderer if TYPE_CHECKING else object):
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
                    'Error processing event %s',
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
