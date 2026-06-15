"""Add custom skill dialog."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, TextArea

from backend.cli.tui.widgets.dialogs import ModalDialog


class GrintaAddSkillDialog(ModalDialog[dict[str, str] | None]):
    """Dialog to create a custom skill dynamically."""

    BINDINGS = [
        *ModalDialog.BINDINGS,
        Binding('ctrl+s', 'save', 'Save', show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id='dialog-container'):
            yield Label('Add Custom Skill', id='dialog-title')
            yield Label('Skill Name (e.g. react_best_practices)', classes='field-label')
            yield Input(id='skill-name')
            yield Label('Instructions (Markdown)', classes='field-label')
            yield TextArea(id='skill-content')
            yield Label('', id='dialog-feedback')
            with Horizontal(id='dialog-buttons'):
                yield Button('Save', id='settings-save', variant='primary')
                yield Button('Cancel', id='settings-cancel')

    def on_mount(self) -> None:
        self.query_one('#skill-name', Input).focus()

    def action_save(self) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'settings-save':
            self._submit()
        elif event.button.id == 'settings-cancel':
            self.dismiss(None)

    def _submit(self) -> None:
        name = self.query_one('#skill-name', Input).value.strip()
        content = self.query_one('#skill-content', TextArea).text.strip()
        if not name:
            self.query_one('#dialog-feedback', Label).update(
                '[#f05757]Skill name required.[/]'
            )
            return
        if not content:
            self.query_one('#dialog-feedback', Label).update(
                '[#f05757]Content required.[/]'
            )
            return
        self.dismiss({'name': name, 'content': content})
