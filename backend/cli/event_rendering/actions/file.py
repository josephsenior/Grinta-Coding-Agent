"""Action renderers — file domain."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.cli._typing import ActionRenderersHost

    _ActionRenderersBase = ActionRenderersHost
else:
    _ActionRenderersBase = object


from backend.cli._typing import ActionRenderersHost
from backend.cli.event_rendering.text_utils import (
    sync_reasoning_after_tool_line as _sync_reasoning_after_tool_line,
)
from backend.cli.display.layout_tokens import (
    ACTIVITY_CARD_TITLE_FILES,
)
from backend.cli.tool_display.orient_tools import (
    file_read_action_model,
)
from backend.ledger.action import (  # noqa: E402
    FileEditAction,
    FileReadAction,
    RecallAction,
)


class _ActionFileMixin(_ActionRenderersBase):
    def _render_file_edit_action(self, action: FileEditAction) -> None:
        self._flush_pending_tool_cards()
        cmd = getattr(action, 'command', '')
        path = action.path
        insert_line = getattr(action, 'insert_line', None)
        start = getattr(action, 'start', 1)
        end = getattr(action, 'end', -1)
        stats: str | None = None
        verb_entry = self._FILE_EDIT_VERBS.get(cmd)
        if verb_entry is not None:
            verb, include_stats = verb_entry
            detail = path
            if include_stats and insert_line is not None:
                stats = f'line {insert_line}'
        elif not cmd:
            end_str = str(end) if end != -1 else 'end'
            verb, detail = 'Edited', f'{path} · {start}:{end_str}'
        else:
            verb, detail = 'Edited', path
        badge_label = self._file_badge_label(action)
        self._buffer_pending_activity(
            title=ACTIVITY_CARD_TITLE_FILES,
            verb=verb,
            detail=detail,
            secondary=stats,
            kind='file_edit',
            badge_label=badge_label,
        )
        thought = getattr(action, 'thought', '') or ''
        _sync_reasoning_after_tool_line(self._reasoning, f'{verb} {detail}', thought)
        self.refresh()

    def _render_recall_action(self, action: RecallAction) -> None:
        # Memory recall is an internal operation - don't show as visible activity
        # It's already indicated in the reasoning display if needed
        self.refresh()

    def _render_file_read_action(self, action: FileReadAction) -> None:
        self._queue_orient_line(file_read_action_model(action))
        thought = getattr(action, 'thought', '') or ''
        _sync_reasoning_after_tool_line(
            self._reasoning,
            f'Read {getattr(action, "path", "")}',
            thought,
        )
        self.refresh()

    @staticmethod
    def _file_badge_label(action: Any) -> str:
        impl_source = getattr(action, 'impl_source', None)
        source_value = getattr(impl_source, 'value', impl_source)
        if source_value == 'file_edit':
            return 'file_edit'
        if source_value == 'default':
            return 'files'
        return 'files'
