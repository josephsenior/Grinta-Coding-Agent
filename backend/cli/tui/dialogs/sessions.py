"""Session manager dialog."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, Label, Select, Static

from backend.cli.theme import NAVY_ERROR, NAVY_READY, NAVY_TEXT_DIM, NAVY_TEXT_MUTED
from backend.cli.tui.dialogs.confirm import GrintaConfirmDialog
from backend.cli.tui.widgets.dialogs import ModalDialog
from backend.core.config import AppConfig


class GrintaSessionsDialog(ModalDialog[str | None]):
    """Native sessions manager for full-screen TUI."""

    DEFAULT_CSS = """
    GrintaSessionsDialog > #dialog-container {
        width: 88;
        max-width: 96%;
        padding: 1 2;
    }
    GrintaSessionsDialog #dialog-subtitle {
        margin-bottom: 0;
    }
    GrintaSessionsDialog #sessions-filters {
        height: 3;
        margin: 1 0 0 0;
    }
    GrintaSessionsDialog #sessions-filters .filter-label {
        width: auto;
        min-width: 6;
        color: #8f9fc1;
        content-align: left middle;
        margin-right: 1;
    }
    GrintaSessionsDialog #sessions-search,
    GrintaSessionsDialog #sessions-limit {
        width: auto;
        margin-left: 0;
    }
    GrintaSessionsDialog #sessions-search {
        width: 1fr;
    }
    GrintaSessionsDialog #sessions-sort {
        width: 14;
        margin-left: 1;
    }
    GrintaSessionsDialog #sessions-limit {
        width: 5;
        margin-left: 1;
    }
    GrintaSessionsDialog #sessions-refresh {
        margin-left: 1;
        min-width: 9;
        height: 1;
    }
    GrintaSessionsDialog #sessions-panel {
        height: auto;
        margin-top: 1;
        background: #08101d;
        border: round #1b233a;
        border-left: heavy #5eead4;
        padding: 0;
    }
    GrintaSessionsDialog #sessions-table {
        height: 12;
        margin: 0;
        border: none;
        background: transparent;
    }
    GrintaSessionsDialog #sessions-preview {
        height: auto;
        max-height: 7;
        margin-top: 0;
        padding: 1;
    }
    GrintaSessionsDialog #dialog-feedback {
        margin-top: 0;
        height: 1;
    }
    GrintaSessionsDialog #dialog-buttons {
        margin-top: 1;
    }
    """

    BINDINGS = [
        *ModalDialog.BINDINGS,
        Binding('f5', 'refresh', 'Refresh', show=False),
        Binding('delete', 'delete_selected', 'Delete', show=False),
    ]

    def __init__(
        self,
        config: AppConfig,
        *,
        search: str | None = None,
        sort_by: str = 'updated',
        limit: int = 20,
        preview_target: str | None = None,
        delete_targets: list[str] | None = None,
    ) -> None:
        super().__init__()
        self._config = config
        self._search = search or ''
        self._sort_by = sort_by
        self._limit = max(1, int(limit))
        self._preview_target = preview_target
        self._delete_targets = delete_targets or []
        self._all_entries: list[tuple[str, dict[str, Any], int, Path]] = []
        self._visible_entries: list[tuple[str, dict[str, Any], int, Path]] = []

    def compose(self) -> ComposeResult:
        options = [
            ('Updated', 'updated'),
            ('Created', 'created'),
            ('Events', 'events'),
            ('Cost', 'cost'),
            ('Model', 'model'),
        ]
        with Vertical(id='dialog-container'):
            yield Label('Sessions', id='dialog-title')
            yield Static(
                f'[{NAVY_TEXT_MUTED}]Resume, preview, or clear saved conversations.[/]',
                id='dialog-subtitle',
            )
            with Horizontal(id='sessions-filters'):
                yield Static('Search', classes='filter-label')
                yield Input(
                    value=self._search,
                    placeholder='title, model, id',
                    id='sessions-search',
                )
                yield Static('Sort', classes='filter-label')
                yield Select(
                    options=options,
                    value=self._sort_by,
                    allow_blank=False,
                    id='sessions-sort',
                )
                yield Static('Limit', classes='filter-label')
                yield Input(
                    value=str(self._limit), restrict=r'\d*', id='sessions-limit'
                )
                yield Button('Refresh', id='sessions-refresh', variant='default')
            with Vertical(id='sessions-panel'):
                yield DataTable(id='sessions-table', zebra_stripes=False)
            yield Static('', id='sessions-preview')
            yield Label('', id='dialog-feedback')
            with Horizontal(id='dialog-buttons'):
                yield Button('Resume', id='sessions-resume', variant='primary')
                yield Button('Delete', id='sessions-delete', variant='error')
                yield Button('Close', id='sessions-close')

    def on_mount(self) -> None:
        table = self.query_one('#sessions-table', DataTable)
        table.cursor_type = 'row'
        table.add_columns('#', 'Session ID', 'Title', 'Events', 'Updated')
        self._refresh_table()
        if self._delete_targets:
            deleted, errors = self._delete_sessions(self._delete_targets)
            self._set_feedback(
                f'Deleted {deleted} session(s). {" ".join(errors)}'.strip()
            )
            self._refresh_table()
        if self._preview_target:
            self._select_target(self._preview_target)
        self.query_one('#sessions-search', Input).focus()

    def action_refresh(self) -> None:
        self._sync_filters_from_ui()
        self._refresh_table()

    async def action_delete_selected(self) -> None:
        sid = self._current_session_id()
        if not sid:
            self._set_feedback('No session selected.', error=True)
            return
        result = await self.app.push_screen_wait(
            GrintaConfirmDialog(
                title='Delete Session',
                body=f'Permanently delete session {sid[:12]}?',
                options=[('cancel', 'Cancel'), ('delete', 'Delete')],
            )
        )
        if result != 'delete':
            return
        deleted, errors = self._delete_sessions([sid])
        if deleted:
            self._set_feedback(f'Deleted session {sid[:12]}.')
        elif errors:
            self._set_feedback(errors[0], error=True)
        self._refresh_table()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == 'sessions-refresh':
            self._sync_filters_from_ui()
            self._refresh_table()
            return
        if bid == 'sessions-delete':
            self.run_worker(self.action_delete_selected(), exclusive=True)
            return
        if bid == 'sessions-resume':
            sid = self._current_session_id()
            if sid:
                self.dismiss(sid)
            else:
                self._set_feedback('No session selected.', error=True)
            return
        if bid == 'sessions-close':
            self.dismiss(None)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._update_preview(event.cursor_row)

    def on_data_table_row_double_clicked(
        self, event: DataTable.RowDoubleClicked
    ) -> None:
        sid = self._current_session_id()
        if sid:
            self.dismiss(sid)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == 'sessions-search':
            self._search = event.value.strip()
            self._refresh_table()
            return
        if event.input.id == 'sessions-limit':
            value = event.value.strip()
            self._limit = int(value) if value.isdigit() and int(value) > 0 else 20
            self._refresh_table()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == 'sessions-sort' and isinstance(event.value, str):
            self._sort_by = event.value
            self._refresh_table()

    def _sync_filters_from_ui(self) -> None:
        self._search = self.query_one('#sessions-search', Input).value.strip()
        limit_text = self.query_one('#sessions-limit', Input).value.strip()
        if limit_text.isdigit() and int(limit_text) > 0:
            self._limit = int(limit_text)
        sort_value = self.query_one('#sessions-sort', Select).value
        if isinstance(sort_value, str) and sort_value:
            self._sort_by = sort_value

    def _set_feedback(self, message: str, *, error: bool = False) -> None:
        style = NAVY_ERROR if error else NAVY_READY
        self.query_one('#dialog-feedback', Label).update(f'[{style}]{message}[/]')

    def _refresh_table(self) -> None:
        from backend.cli.session.session_manager import (
            _filter_sessions_fuzzy,
            _find_sessions_root,
            _list_session_entries,
        )

        storage_root = _find_sessions_root(self._config)
        table = self.query_one('#sessions-table', DataTable)
        table.clear(columns=False)
        if storage_root is None:
            self._all_entries = []
            self._visible_entries = []
            self._set_feedback('No session storage found.', error=True)
            self.query_one('#sessions-preview', Static).update('')
            return

        entries = _list_session_entries(storage_root, sort_by=self._sort_by)
        self._all_entries = entries
        if self._search:
            entries = _filter_sessions_fuzzy(entries, self._search)
        self._visible_entries = entries[: self._limit]
        for i, (sid, meta, event_count, _path) in enumerate(self._visible_entries, 1):
            title = str(meta.get('title') or meta.get('name') or '-')
            updated = str(meta.get('last_updated_at') or meta.get('created_at') or '-')[
                :19
            ]
            table.add_row(str(i), sid[:12], title, str(event_count), updated, key=sid)

        if self._visible_entries:
            table.move_cursor(row=0, column=0, animate=False, scroll=False)
            self._update_preview(0)
            total = len(self._all_entries)
            shown = len(self._visible_entries)
            suffix = f' (showing {shown} of {total})' if shown < total else ''
            self._set_feedback(f'{shown} session(s) loaded{suffix}.')
        else:
            self.query_one('#sessions-preview', Static).update('')
            if self._search:
                self._set_feedback(
                    f'No sessions matching "{self._search}".', error=True
                )
            else:
                self._set_feedback('No sessions found.', error=True)

    def _select_target(self, target: str) -> None:
        from backend.cli.session.session_manager import _resolve_target

        resolved = _resolve_target(self._visible_entries, target)
        if resolved is None:
            self._set_feedback(f"No session at '{target}'", error=True)
            return
        sid = resolved[0]
        for idx, item in enumerate(self._visible_entries):
            if item[0] == sid:
                table = self.query_one('#sessions-table', DataTable)
                table.move_cursor(row=idx, column=0, animate=False, scroll=True)
                self._update_preview(idx)
                break

    def _current_session_id(self) -> str | None:
        table = self.query_one('#sessions-table', DataTable)
        row_index = table.cursor_row
        if row_index < 0 or row_index >= len(self._visible_entries):
            return None
        return self._visible_entries[row_index][0]

    _PREVIEW_FIELDS: list[tuple[str, str, str]] = [
        ('title', 'title', 'Title'),
        ('name', 'title', 'Title'),
        ('llm_model', 'model', 'Model'),
        ('selected_repository', 'repo', 'Repository'),
        ('selected_branch', 'branch', 'Branch'),
        ('trigger', 'trigger', 'Trigger'),
    ]

    def _build_preview_line(self, label: str, value: str) -> str | None:
        if not value:
            return None
        return f'[#c8d4e8]{label}:[/] {value}'

    def _build_preview_tokens_line(self, meta: dict[str, Any]) -> str | None:
        total_tokens = int(meta.get('total_tokens') or 0)
        if not total_tokens:
            return None
        prompt_tokens = int(meta.get('prompt_tokens') or 0)
        completion_tokens = int(meta.get('completion_tokens') or 0)
        return (
            f'[#c8d4e8]Tokens:[/] {total_tokens:,} total'
            f'  [{NAVY_TEXT_DIM}](p:{prompt_tokens:,} c:{completion_tokens:,})[/]'
        )

    def _build_preview_metadata_lines(self, meta: dict[str, Any]) -> list[str]:
        lines = []
        seen_labels = set()
        for key, _, label in self._PREVIEW_FIELDS:
            if label in seen_labels:
                continue
            value = str(meta.get(key) or '')
            if line := self._build_preview_line(label, value):
                lines.append(line)
                seen_labels.add(label)
        return lines

    def _build_preview_lines(
        self, sid: str, meta: dict[str, Any], event_count: int
    ) -> list[str]:
        lines = [f'[#c8d4e8]ID:[/] {sid}']
        lines.extend(self._build_preview_metadata_lines(meta))
        lines.append(f'[#c8d4e8]Events:[/] {event_count}')
        cost = float(meta.get('accumulated_cost') or 0)
        if cost:
            lines.append(f'[#c8d4e8]Cost:[/] ${cost:.4f}')
        if line := self._build_preview_tokens_line(meta):
            lines.append(line)
        updated = str(meta.get('last_updated_at') or meta.get('created_at') or '')
        if updated:
            lines.append(f'[#c8d4e8]Updated:[/] {updated[:19]}')
        created = str(meta.get('created_at') or '')
        if created and str(meta.get('last_updated_at') or '') != created:
            lines.append(f'[#c8d4e8]Created:[/] {created[:19]}')
        return lines

    def _update_preview(self, row_index: int) -> None:
        if row_index < 0 or row_index >= len(self._visible_entries):
            self.query_one('#sessions-preview', Static).update('')
            return
        sid, meta, event_count, _path = self._visible_entries[row_index]
        lines = self._build_preview_lines(sid, meta, event_count)
        self.query_one('#sessions-preview', Static).update('\n'.join(lines))

    def _delete_sessions(self, targets: list[str]) -> tuple[int, list[str]]:
        from backend.cli.session.session_manager import (
            _resolve_target,
            _session_dir_for,
        )

        if not self._all_entries:
            return 0, ['No session storage found.']

        deleted = 0
        errors: list[str] = []
        for target in targets:
            resolved = _resolve_target(self._all_entries, target)
            if resolved is None:
                errors.append(f"No session at '{target}'.")
                continue
            sid = resolved[0]
            try:
                shutil.rmtree(_session_dir_for(resolved), ignore_errors=False)
                deleted += 1
            except Exception as exc:
                errors.append(f'{sid[:12]}: {exc}')
        return deleted, errors
