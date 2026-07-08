"""Action renderers — meta domain."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.cli._typing import ActionRenderersHost

    _ActionRenderersBase = ActionRenderersHost
else:
    _ActionRenderersBase = object

from backend.cli._typing import ActionRenderersHost
from backend.cli.display.layout_tokens import (
    ACTIVITY_CARD_TITLE_DELEGATION,
)
from backend.cli.event_rendering.delegate import (
    summarize_delegate_action as _summarize_delegate_action,
)
from backend.ledger.action import (  # noqa: E402
    CondensationAction,
    DelegateTaskAction,
    TaskTrackingAction,
)


class _ActionMetaMixin(_ActionRenderersBase):
    def _render_task_tracking_action(self, action: TaskTrackingAction) -> None:
        command = str(getattr(action, 'command', '') or '').strip().lower()
        task_list = getattr(action, 'task_list', None)
        if command == 'update' and isinstance(task_list, list):
            self._set_task_panel(task_list)
        self.refresh()

    def _render_condensation_action(self, action: CondensationAction) -> None:
        count = getattr(self, '_condensation_count', 0) + 1
        self._condensation_count = count
        suffix = self._ordinal_suffix(count)

        self._ensure_reasoning()
        self._reasoning.update_action(f'Compressing context ({count}{suffix})…')

        host = getattr(self, '_host', None)
        if host is not None:
            host._hud.update_condensation_count(count)
        self.refresh()

    @staticmethod
    def _ordinal_suffix(n: int) -> str:
        if n % 10 == 1 and n % 11 != 1:
            return 'st'
        if n % 10 == 2 and n % 11 != 2:
            return 'nd'
        if n % 10 == 3 and n % 11 != 3:
            return 'rd'
        return 'th'

    def _render_delegate_task_action(self, action: DelegateTaskAction) -> None:
        self._flush_pending_tool_cards()
        self._reset_delegate_panel(batch_id=action.id if action.id > 0 else None)
        desc_display, secondary = _summarize_delegate_action(action)
        self._buffer_pending_activity(
            title=ACTIVITY_CARD_TITLE_DELEGATION,
            verb='Delegated',
            detail=desc_display,
            secondary=secondary,
            kind='delegate',
            badge_label='workers',
        )
        self.refresh()
