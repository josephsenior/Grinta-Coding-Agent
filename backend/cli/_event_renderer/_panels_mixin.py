"""Panels methods for CLIEventRenderer.

Task/delegate panels & metrics (_set_task_panel/_set_delegate_panel/_update_metrics/_check_budget).

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

class _EventRendererPanelsMixin(CLIEventRenderer if TYPE_CHECKING else object):
    """Mixin class — see module docstring."""

    def _set_task_panel(self, task_list: list[dict[str, Any]]) -> None:
        """Replace the visible task tracker panel with the latest known state."""
        self._task_panel = _build_task_panel(task_list)
        self._task_panel_signature = _task_panel_signature(task_list)
        if (
            self._live is None
            and self._task_panel_signature != self._last_printed_task_panel_signature
        ):
            self._print_or_buffer(self._task_panel)
            self._last_printed_task_panel_signature = self._task_panel_signature
    def _set_delegate_panel(self) -> None:
        """Replace the visible delegated-worker panel with the latest known state."""
        self._delegate_panel = _build_delegate_worker_panel(self._delegate_workers)
        self._delegate_panel_signature = _delegate_worker_panel_signature(
            self._delegate_workers
        )
        # Update reasoning display to show delegate state instead of "Thinking"
        self._update_reasoning_for_delegate_state()
        if (
            self._live is None
            and self._delegate_panel_signature
            != self._last_printed_delegate_panel_signature
        ):
            self._print_or_buffer(self._delegate_panel)
            self._last_printed_delegate_panel_signature = self._delegate_panel_signature
    def _update_reasoning_for_delegate_state(self) -> None:
        """Update the reasoning display to reflect delegate worker state."""
        if not self._delegate_workers:
            return
        running = sum(
            1
            for w in self._delegate_workers.values()
            if w.get('status') in ('running', 'starting')
        )
        done = sum(
            1 for w in self._delegate_workers.values() if w.get('status') == 'done'
        )
        failed = sum(
            1 for w in self._delegate_workers.values() if w.get('status') == 'failed'
        )
        total = len(self._delegate_workers)

        parts = []
        if running:
            parts.append(f'{running} running')
        if done:
            parts.append(f'{done} done')
        if failed:
            parts.append(f'{failed} failed')

        status_text = ', '.join(parts) if parts else f'{total} worker(s)'
        self._ensure_reasoning()
        self._reasoning.commit_thought(f'Waiting for {total} worker(s) · {status_text}')
    def _reset_delegate_panel(self, *, batch_id: int | None) -> None:
        """Start a fresh delegated-worker panel for a new delegation batch."""
        self._delegate_workers = {}
        self._delegate_batch_id = batch_id
        self._delegate_panel = None
        self._delegate_panel_signature = None
        self._last_printed_delegate_panel_signature = None
        # Reset reasoning back from delegate-aware state
        if self._reasoning.active:
            self._reasoning.update_action('')
    @staticmethod
    def _format_command_display(command: str, *, limit: int = 96) -> str:
        display = ' '.join(command.split())
        if not display:
            return '(empty command)'
        if len(display) > limit:
            return display[: limit - 1] + '…'
        return display
    def _update_metrics(self, event: Any) -> None:
        llm_metrics = getattr(event, 'llm_metrics', None)
        if llm_metrics is not None:
            self._hud.update_from_llm_metrics(llm_metrics)
            self._reasoning.update_cost(self._hud.state.cost_usd)
            self._check_budget()
    def _check_budget(self) -> None:
        if not self._max_budget or self._max_budget <= 0:
            return
        cost = self._hud.state.cost_usd
        if cost >= self._max_budget and not self._budget_warned_100:
            self._budget_warned_100 = True
            self._print_or_buffer(
                Panel(
                    Text(
                        f'Budget limit reached: ${cost:.4f} / ${self._max_budget:.4f}',
                        style=CLR_ERR_ICON,
                    ),
                    title=Text('Budget Exceeded', style=CLR_ERR_ICON),
                    title_align='left',
                    border_style=CLR_STATUS_ERR,
                    padding=(1, 2),
                )
            )
        elif cost >= self._max_budget * 0.8 and not self._budget_warned_80:
            self._budget_warned_80 = True
            self._print_or_buffer(
                Panel(
                    Text(
                        f'Approaching budget: ${cost:.4f} / ${self._max_budget:.4f} (80%)',
                        style=CLR_WARN_BODY,
                    ),
                    title=Text('Budget Warning', style=CLR_WARN_ICON),
                    title_align='left',
                    border_style=CLR_STATUS_WARN,
                    padding=(1, 2),
                )
            )
