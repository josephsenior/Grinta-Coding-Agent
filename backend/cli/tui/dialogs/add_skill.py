"""Add custom skill dialog."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, Static, TextArea

from backend.cli.tui.widgets.dialogs import ModalDialog

DEFAULT_SKILL_TEMPLATE = """# Skill Name

## When to use


## Instructions

"""


class GrintaAddSkillDialog(ModalDialog[dict[str, str] | None]):
    """Dialog to create a custom skill dynamically."""

    BINDINGS = [
        *ModalDialog.BINDINGS,
        Binding('ctrl+s', 'save', 'Save', show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id='dialog-container'):
            yield Label('Add Custom Skill', id='dialog-title')
            yield Static(
                'Create a reusable instruction file for future sessions.',
                id='dialog-subtitle',
            )
            yield Label('Skill name', classes='field-label')
            yield Input(id='skill-name', placeholder='my-skill')
            yield Label('Instructions (Markdown)', classes='field-label')
            yield TextArea(id='skill-content')
            yield Label('', id='dialog-feedback')
            with Horizontal(id='dialog-buttons'):
                yield Button('Save', id='settings-save', variant='primary')
                yield Button('Cancel', id='settings-cancel')

    def on_mount(self) -> None:
        self.query_one('#skill-content', TextArea).load_text(DEFAULT_SKILL_TEMPLATE)
        self.query_one('#skill-name', Input).focus()

    def action_save(self) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'settings-save':
            self._submit()
        elif event.button.id == 'settings-cancel':
            self.dismiss(None)

    def _submit(self) -> None:
        feedback = self.query_one('#dialog-feedback', Label)
        name = self.query_one('#skill-name', Input).value.strip()
        content = self.query_one('#skill-content', TextArea).text.strip()
        if not name:
            feedback.update('[#f05757]Skill name required.[/]')
            return
        if '/' in name or '\\' in name:
            feedback.update('[#f05757]Use a simple name without path separators.[/]')
            return
        stem = name.removesuffix('.md')
        skill_path = Path.home() / '.grinta' / 'skills' / f'{stem}.md'
        if skill_path.exists():
            feedback.update(f'[#f05757]Skill already exists: {stem}.md[/]')
            return
        if not content:
            feedback.update('[#f05757]Content required.[/]')
            return
        self.dismiss({'name': stem, 'content': content})
