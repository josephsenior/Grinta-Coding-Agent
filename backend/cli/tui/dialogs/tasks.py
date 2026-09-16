"""Tasks drawer — full task list, opened on demand.

Task progress used to occupy a permanent sidebar column. That's replaced by a
compact one-line summary in the HUD (see ``HUD.update_tasks`` /
``ScreenLifecycleMixin`` HUD rendering), which costs one row instead of a
column and disappears entirely when there are no tasks. This dialog is where
the full list — every task, its status, its id — lives for the moments you
actually want it, mirroring the same drawer pattern the HUD's compact-mode
"Controls" button already uses for session controls.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label

from backend.cli.event_rendering.panels import task_panel_signature
from backend.cli.theme import NAVY_BRAND
from backend.cli.tui.widgets.collapsible import CollapsibleSection, SidebarRow
from backend.cli.tui.widgets.dialogs import ModalDialog
from backend.core.tasks.task_status import TASK_STATUS_DONE


class GrintaTasksDialog(ModalDialog[None]):
    """Read-only snapshot of the current task plan."""

    DEFAULT_CSS = """
    GrintaTasksDialog > #dialog-container {
        width: 66;
        max-width: 92%;
        height: auto;
        max-height: 90%;
    }
    GrintaTasksDialog #tasks-body {
        height: auto;
        max-height: 40;
        overflow-y: auto;
        scrollbar-size-vertical: 1;
        scrollbar-color: #64748b #0f172a;
    }
    """

    def __init__(self, renderer: Any) -> None:
        super().__init__()
        self._renderer = renderer

    def compose(self) -> ComposeResult:
        signature = task_panel_signature(getattr(self._renderer, '_task_list', []))
        total = len(signature)
        done = sum(1 for _tid, status, _desc in signature if status == TASK_STATUS_DONE)
        title = f'Tasks · {done}/{total} done' if total else 'Tasks'

        with Vertical(id='dialog-container'):
            yield Label('Tasks', id='dialog-title')
            with Vertical(id='tasks-body'):
                yield CollapsibleSection(
                    title=title,
                    content='No tasks yet',
                    collapsed=False,
                    accent_color=NAVY_BRAND,
                    section_icon='▣',
                    id='tasks-list',
                )

    def on_mount(self) -> None:
        section = self.query_one('#tasks-list', CollapsibleSection)
        signature = task_panel_signature(getattr(self._renderer, '_task_list', []))
        items = self._renderer._build_task_sidebar_items(signature)
        section.set_items(items)

        active_task_id = next(
            (tid for tid, status, _desc in signature if status == 'in_progress'),
            None,
        )
        if active_task_id:
            for row in section.query(SidebarRow):
                if row.item_id == f'task:{active_task_id}':
                    row.add_class('-active-task')

    def on_sidebar_row_selected(self, event: Any) -> None:
        """Selecting a task closes the drawer and jumps the transcript to it.

        Same "follow live activity" behavior the old permanent sidebar had
        for a task row click.
        """
        if not isinstance(event, SidebarRow.Selected) or not event.item_id:
            return
        if not event.item_id.startswith('task:'):
            return
        task_id = event.item_id.split(':', 1)[1]
        desc = 'Unknown task'
        for tid, _status, description in task_panel_signature(
            getattr(self._renderer, '_task_list', [])
        ):
            if tid == task_id:
                desc = description or desc
                break

        screen = self._renderer._tui
        self.dismiss(None)
        try:
            screen._get_display().force_scroll_end()
        except Exception:
            pass
        screen.notify(f'Following live activity · {desc}', severity='info', timeout=2.5)
