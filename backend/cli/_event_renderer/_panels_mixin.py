"""Panels methods for CLIEventRenderer.

Task/delegate panels & metrics (_set_task_panel/_set_delegate_panel/_update_metrics/_check_budget).

Extracted from backend/cli/event_renderer.py to keep the parent module
under the per-file LOC budget. All methods rely on attributes/methods
defined on CLIEventRenderer; this mixin is meant to be combined with
that class via multiple inheritance.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from rich.panel import Panel
from rich.text import Text

from backend.cli._event_renderer.panels import (
    build_delegate_worker_panel as _build_delegate_worker_panel,
)
from backend.cli._event_renderer.panels import (
    build_task_panel as _build_task_panel,
)
from backend.cli._event_renderer.panels import (
    delegate_worker_panel_signature as _delegate_worker_panel_signature,
)
from backend.cli._event_renderer.panels import (
    task_panel_signature as _task_panel_signature,
)
from backend.cli.theme import (
    CLR_ERR_ICON,
    CLR_STATUS_ERR,
    CLR_STATUS_WARN,
    CLR_WARN_BODY,
    CLR_WARN_ICON,
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

    def _count_workers_by_status(self, statuses: frozenset[str]) -> int:
        return sum(
            1 for w in self._delegate_workers.values() if w.get('status') in statuses
        )

    def _delegate_status_text(self, total: int) -> str:
        running = self._count_workers_by_status(frozenset({'running', 'starting'}))
        done = self._count_workers_by_status(frozenset({'done'}))
        failed = self._count_workers_by_status(frozenset({'failed'}))
        parts: list[str] = []
        if running:
            parts.append(f'{running} running')
        if done:
            parts.append(f'{done} done')
        if failed:
            parts.append(f'{failed} failed')
        return ', '.join(parts) if parts else f'{total} worker(s)'

    def _update_reasoning_for_delegate_state(self) -> None:
        """Update the reasoning display to reflect delegate worker state."""
        if not self._delegate_workers:
            return
        total = len(self._delegate_workers)
        status_text = self._delegate_status_text(total)
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
