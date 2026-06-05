"""_AppRendererEventProcessorMixin: event drain/activity + per-event processing + diff extraction."""

from __future__ import annotations

from backend.cli.tui._app_constants import (
    _TUI_HISTORY_RENDER_LIMIT,
    _TUI_PENDING_EVENT_LIMIT,
)
from backend.cli.tui._app_renderer_event_classify import (
    _is_full_autonomy,
    _is_live_thinking_event,
)
from backend.cli.tui._app_renderer_event_diff import (
    _extract_file_edit_diff,
    _extract_file_edit_group_rows,
    _extract_file_observation_diff,
    _extract_git_file_diff,
    _should_replace_task_list_from_event,
)
from backend.cli.tui._app_renderer_event_drain import (
    _on_event,
    _signal_activity,
    drain_events,
    wait_for_activity,
)
from backend.cli.tui._app_renderer_event_helpers import (
    _compact_file_card_path,
    _has_pending_file_card,
    _remember_pending_file_card,
    _take_pending_file_card,
)
from backend.cli.tui._app_renderer_event_processor import (
    _process_event,
    _show_compaction_started_card,
)

__all__ = [
    '_AppRendererEventProcessorMixin',
    '_TUI_HISTORY_RENDER_LIMIT',
    '_TUI_PENDING_EVENT_LIMIT',
]


class _AppRendererEventProcessorMixin:
    """event drain/activity + per-event processing + diff extraction."""

    @staticmethod
    def _compact_file_card_path(path: str) -> str:
        return _compact_file_card_path(None, path)

    def _remember_pending_file_card(self, attr: str, path: str, widget) -> None:
        _remember_pending_file_card(self, attr, path, widget)

    def _take_pending_file_card(self, attr: str, path: str):
        return _take_pending_file_card(self, attr, path)

    def _has_pending_file_card(self, attr: str, path: str) -> bool:
        return _has_pending_file_card(self, attr, path)

    def _is_full_autonomy(self) -> bool:
        return _is_full_autonomy(self)

    def drain_events(self) -> None:
        drain_events(self)

    async def wait_for_activity(self, wait_timeout_sec: float = 0.5):
        return await wait_for_activity(self, wait_timeout_sec)

    def _on_event(self, event) -> None:
        _on_event(self, event)

    def _signal_activity(self, should_schedule_drain: bool) -> None:
        _signal_activity(self, should_schedule_drain)

    def _is_live_thinking_event(self, event) -> bool:
        return _is_live_thinking_event(self, event)

    def _show_compaction_started_card(self) -> None:
        _show_compaction_started_card(self)

    def _process_event(self, event) -> None:
        _process_event(self, event)

    def _should_replace_task_list_from_event(self, event) -> bool:
        return _should_replace_task_list_from_event(self, event)

    def _extract_file_observation_diff(self, event):
        return _extract_file_observation_diff(self, event)

    def _extract_file_edit_group_rows(self, event):
        return _extract_file_edit_group_rows(self, event)

    def _extract_file_edit_diff(self, event):
        return _extract_file_edit_diff(self, event)

    def _extract_git_file_diff(self, path: str):
        return _extract_git_file_diff(self, path)
