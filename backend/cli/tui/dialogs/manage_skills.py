"""Skills management dialog."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Label

import backend
from backend.cli.event_rendering.sidebar import is_user_skill, load_sidebar_skills
from backend.cli.tui.dialogs.add_skill import GrintaAddSkillDialog
from backend.cli.tui.dialogs.confirm import GrintaConfirmDialog
from backend.cli.tui.widgets.dialogs import ModalDialog

class GrintaManageSkillsDialog(ModalDialog[bool]):
    """List, add, edit, and remove skills."""

    DEFAULT_CSS = """
    GrintaManageSkillsDialog #skills-panel {
        height: auto;
        margin-top: 1;
        background: #08101d;
        border: round #1b233a;
        border-left: heavy #c792ea;
        padding: 0;
    }
    GrintaManageSkillsDialog #skills-table {
        height: 12;
        margin: 0;
        border: none;
        background: transparent;
    }
    """

    BINDINGS = [
        *ModalDialog.BINDINGS,
        Binding('enter', 'edit_selected', 'Edit', show=False),
        Binding('delete', 'delete_selected', 'Delete', show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._changed = False
        self._skills: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical(id='dialog-container'):
            yield Label('Skills', id='dialog-title')
            with Vertical(id='skills-panel'):
                yield DataTable(id='skills-table', zebra_stripes=False)
            yield Label('', id='dialog-feedback')
            with Horizontal(id='dialog-buttons'):
                yield Button('Add', id='skills-add', variant='primary')
                yield Button('Edit', id='skills-edit')
                yield Button('Delete', id='skills-delete', variant='error')
                yield Button('Close', id='skills-close')

    def on_mount(self) -> None:
        table = self.query_one('#skills-table', DataTable)
        table.cursor_type = 'row'
        table.add_columns('Name')
        self._refresh_table()

    def action_edit_selected(self) -> None:
        self.run_worker(self._edit_skill(), exclusive=True)

    def action_delete_selected(self) -> None:
        self.run_worker(self._delete_skill(), exclusive=True)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.query_one('#dialog-feedback', Label).update('')

    def on_data_table_row_double_clicked(
        self, event: DataTable.RowDoubleClicked
    ) -> None:
        self.run_worker(self._edit_skill(), exclusive=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == 'skills-close':
            self.dismiss(self._changed)
            return
        if bid == 'skills-add':
            self.run_worker(self._add_skill(), exclusive=True)
            return
        if bid == 'skills-edit':
            self.run_worker(self._edit_skill(), exclusive=True)
            return
        if bid == 'skills-delete':
            self.run_worker(self._delete_skill(), exclusive=True)

    def _set_feedback(self, message: str, *, error: bool = False) -> None:
        color = '#f05757' if error else '#5eead4'
        self.query_one('#dialog-feedback', Label).update(f'[{color}]{message}[/]')

    def _selected_skill(self) -> str | None:
        if not self._skills:
            return None
        table = self.query_one('#skills-table', DataTable)
        row_index = table.cursor_row
        if row_index is None or row_index < 0 or row_index >= len(self._skills):
            return None
        return self._skills[row_index]

    def _refresh_table(self) -> None:
        self._skills = load_sidebar_skills()
        table = self.query_one('#skills-table', DataTable)
        table.clear()
        if not self._skills:
            table.add_row('(none configured)')
            return
        for skill in self._skills:
            table.add_row(skill)

    def _read_skill_content(self, stem: str) -> str | None:
        read_only = not is_user_skill(stem)
        if read_only:
            playbook_path = (
                Path(backend.__file__).resolve().parent / 'playbooks' / f'{stem}.md'
            )
            try:
                return playbook_path.read_text(encoding='utf-8')
            except OSError:
                return None
        skill_path = Path.home() / '.grinta' / 'skills' / f'{stem}.md'
        try:
            return skill_path.read_text(encoding='utf-8')
        except OSError:
            return None

    async def _add_skill(self) -> None:
        result = await self.app.push_screen_wait(GrintaAddSkillDialog())
        if not result:
            return
        skills_dir = Path.home() / '.grinta' / 'skills'
        skills_dir.mkdir(parents=True, exist_ok=True)
        skill_path = skills_dir / f'{result["name"]}.md'
        try:
            skill_path.write_text(result['content'], encoding='utf-8')
        except OSError as exc:
            self._set_feedback(str(exc), error=True)
            return
        self._changed = True
        self._refresh_table()
        self._set_feedback(f'Added {result["name"]}.')

    async def _edit_skill(self) -> None:
        stem = self._selected_skill()
        if not stem:
            self._set_feedback('Select a skill first.', error=True)
            return
        content = self._read_skill_content(stem)
        if content is None:
            self._set_feedback(f'Skill not found: {stem}', error=True)
            return
        read_only = not is_user_skill(stem)
        result = await self.app.push_screen_wait(
            GrintaAddSkillDialog(
                edit_name=stem,
                edit_content=content,
                read_only=read_only,
            )
        )
        if not result or read_only:
            return
        skill_path = Path.home() / '.grinta' / 'skills' / f'{stem}.md'
        try:
            skill_path.write_text(result['content'], encoding='utf-8')
        except OSError as exc:
            self._set_feedback(str(exc), error=True)
            return
        self._changed = True
        self._refresh_table()
        self._set_feedback(f'Updated {stem}.')

    async def _delete_skill(self) -> None:
        stem = self._selected_skill()
        if not stem:
            self._set_feedback('Select a skill first.', error=True)
            return
        if not is_user_skill(stem):
            self._set_feedback(f"'{stem}' cannot be removed.", error=True)
            return
        result = await self.app.push_screen_wait(
            GrintaConfirmDialog(
                title='Delete Skill',
                body=f"Remove '{stem}'?",
                options=[('cancel', 'Cancel'), ('delete', 'Remove')],
            )
        )
        if result != 'delete':
            return
        skill_path = Path.home() / '.grinta' / 'skills' / f'{stem}.md'
        try:
            if skill_path.exists():
                skill_path.unlink()
        except OSError as exc:
            self._set_feedback(str(exc), error=True)
            return
        self._changed = True
        self._refresh_table()
        self._set_feedback(f'Removed {stem}.')
