"""Live methods for CLIEventRenderer.

Live display lifecycle (start/stop/refresh/suspend/begin/clear/wait).

Extracted from backend/cli/event_renderer.py to keep the parent module
under the per-file LOC budget. All methods rely on attributes/methods
defined on CLIEventRenderer; this mixin is meant to be combined with
that class via multiple inheritance.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING

from rich.live import Live

from backend.core.enums import AgentState

if TYPE_CHECKING:
    from backend.cli.event_renderer import CLIEventRenderer


logger = logging.getLogger(__name__)


class LiveMixin(CLIEventRenderer if TYPE_CHECKING else object):
    """Mixin class — see module docstring."""

    def start_live(self) -> None:
        """Create and start a Rich Live display for the current agent turn.

        In accessible mode no Live display is created — output is printed
        directly instead.
        """
        self.drain_events()
        if self._accessible:
            return
        if self._live is not None:
            return
        live = Live(
            self,
            console=self._console,
            auto_refresh=False,
            transient=True,  # erases on stop — we print final output ourselves
            # Use 'scroll' for better viewport management when content exceeds
            # terminal height. This prevents the visual mess where old content
            # overlaps with new.
            vertical_overflow='scroll',  # type: ignore[arg-type]
        )
        live.start()
        self._live = live
        self.refresh(force=True)

    def stop_live(self) -> None:
        """Stop the Rich Live display.

        In accessible mode, flush output directly instead.
        """
        # Process any last events while Live is still active so they land
        # in the console scrollback immediately (avoiding run_in_terminal delay).
        self.drain_events()

        # In accessible mode, flush pending output directly.
        if self._accessible:
            self._flush_thinking_block()
            self._console.print()
            try:
                self._console.show_cursor(True)
            except Exception:
                pass
            return
        # Flush any remaining thinking before the Live panel disappears.
        self._flush_thinking_block()
        live = self._live
        if live is None:
            try:
                self._console.show_cursor(True)
            except Exception:
                pass
            return
        self._live = None
        # Task panel is now shown in sidebar - no need to print separately
        if (
            self._delegate_panel is not None
            and self._delegate_panel_signature
            != self._last_printed_delegate_panel_signature
        ):
            self._console.print(self._delegate_panel)
            self._last_printed_delegate_panel_signature = self._delegate_panel_signature
        try:
            live.stop()
        except Exception:
            logger.debug('Live.stop() failed', exc_info=True)
        # Rich usually restores the cursor, but prompt_toolkit may still think the
        # screen layout is pre-Live; force-visible cursor before the next prompt.
        try:
            self._console.show_cursor(True)
        except Exception:
            pass

    _REFRESH_MIN_INTERVAL: float = 0.05

    def refresh(self, *, force: bool = False) -> None:
        """Redraw the Live display if active.

        In accessible mode, flush pending events and return immediately.

        When *force* is False the call is throttled so rapid-fire streaming
        tokens do not saturate the terminal with redraws.

        However, when content exceeds terminal height and needs scrolling,
        we skip throttle to ensure the viewport updates properly.
        """
        if self._accessible:
            self.drain_events()
            return
        if self._live is None:
            return
        now = time.monotonic()
        has_streaming_content = bool(self._streaming_accumulated)
        if (
            not force
            and not has_streaming_content
            and (now - self._last_refresh_time) < self._REFRESH_MIN_INTERVAL
        ):
            return
        self._last_refresh_time = now
        current_size = (self._console.width, self._console.height)
        if current_size != self._last_console_size:
            self._last_console_size = current_size
            force = True
        try:
            self._live.update(self, refresh=force)
        except Exception:
            logger.debug('Live.update() failed', exc_info=True)

    @contextmanager
    def suspend_live(self):
        """Stop/start Live around a block (fallback for non-interactive input)."""
        if self._accessible:
            yield
            return
        live = self._live
        if live is None:
            yield
            return
        was_active = True
        try:
            live.stop()
        except Exception:
            logger.debug('Live.stop() failed during suspend', exc_info=True)
            was_active = False
        self._live = None
        try:
            yield
        finally:
            if was_active and self._live is None:
                try:
                    live.start()
                    self._live = live
                except Exception:
                    logger.debug('Live.start() failed during resume', exc_info=True)
            self.refresh()

    def begin_turn(self) -> None:
        """Snapshot metrics and mark the agent as running."""
        self._pending_shell_command = None
        self._pending_shell_action = None
        self._pending_shell_title = None
        self._pending_shell_is_internal = False
        self._pending_activity_card = None
        self._activity_turn_header_emitted = False
        self._last_committed_reasoning_lines = None
        self._current_state = AgentState.RUNNING
        self._hud.update_ledger('Healthy')
        self._hud.update_agent_state('Running')
        self._state_event.clear()
        self._turn_start_cost = self._hud.state.cost_usd
        self._turn_start_tokens = self._hud.state.context_tokens
        self._turn_start_calls = self._hud.state.llm_calls
        self._reasoning.set_cost_baseline(self._hud.state.cost_usd)
        self.refresh()

    async def wait_for_state_change(
        self, wait_timeout_sec: float = 0.25
    ) -> AgentState | None:
        if self._pending_events:
            return self._current_state
        try:
            await asyncio.wait_for(self._state_event.wait(), timeout=wait_timeout_sec)
        except asyncio.TimeoutError:
            return self._current_state
        if not self._pending_events:
            self._state_event.clear()
        return self._current_state

    def clear_history(self) -> None:
        self._pending_shell_command = None
        self._pending_shell_action = None
        self._pending_shell_title = None
        self._pending_shell_is_internal = False
        self._pending_activity_card = None
        self._activity_turn_header_emitted = False
        self._task_panel = None
        self._task_panel_signature = None
        self._last_printed_task_panel_signature = None
        self._delegate_workers = {}
        self._delegate_batch_id = None
        self._delegate_panel = None
        self._delegate_panel_signature = None
        self._last_printed_delegate_panel_signature = None
        self._last_committed_reasoning_lines = None
        self._clear_streaming_preview()
        self._reasoning.stop()
        self.refresh()
