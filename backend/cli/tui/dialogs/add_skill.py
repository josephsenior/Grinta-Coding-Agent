"""Add or edit custom skill dialog."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, TextArea

from backend.cli.tui.widgets.dialogs import ModalDialog

DEFAULT_SKILL_TEMPLATE = """# Skill Name

## When to use


## Instructions

"""


class GrintaAddSkillDialog(ModalDialog[dict[str, str] | None]):
    """Dialog to create or edit a custom skill."""

    BINDINGS = [
        *ModalDialog.BINDINGS,
        Binding('ctrl+s', 'save', 'Save', show=False),
    ]

    def __init__(
        self,
        *,
        edit_name: str | None = None,
        edit_content: str | None = None,
        read_only: bool = False,
    ) -> None:
        super().__init__()
        self._edit_name = (edit_name or '').strip() or None
        self._edit_content = edit_content
        self._read_only = read_only

    def compose(self) -> ComposeResult:
        if self._read_only:
            title = 'View Skill'
        elif self._edit_name:
            title = 'Edit Skill'
        else:
            title = 'Add Skill'
        with Vertical(id='dialog-container'):
            yield Label(title, id='dialog-title')
            yield Label('Skill name', classes='field-label')
            yield Input(id='skill-name', placeholder='my-skill')
            yield Label('Instructions (Markdown)', classes='field-label')
            yield TextArea(id='skill-content')
            yield Label('', id='dialog-feedback')
            with Horizontal(id='dialog-buttons'):
                if not self._read_only:
                    yield Button('Save', id='settings-save', variant='primary')
                yield Button(
                    'Close' if self._read_only else 'Cancel',
                    id='settings-cancel',
                )

    def on_mount(self) -> None:
        content_area = self.query_one('#skill-content', TextArea)
        name_input = self.query_one('#skill-name', Input)
        if self._edit_name:
            name_input.value = self._edit_name
            name_input.disabled = True
        if self._edit_content is not None:
            content_area.load_text(self._edit_content)
        elif not self._edit_name:
            content_area.load_text(DEFAULT_SKILL_TEMPLATE)
        if self._read_only:
            content_area.disabled = True
            self.query_one('#settings-cancel', Button).focus()
        elif self._edit_name:
            content_area.focus()
        else:
            name_input.focus()

    def action_save(self) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'settings-save':
            self._submit()
        elif event.button.id == 'settings-cancel':
            self.dismiss(None)

    def _submit(self) -> None:
        if self._read_only:
            self.dismiss(None)
            return
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
        if not self._edit_name:
            skill_path = Path.home() / '.grinta' / 'skills' / f'{stem}.md'
            if skill_path.exists():
                feedback.update(f'[#f05757]Skill already exists: {stem}.md[/]')
                return
        if not content:
            feedback.update('[#f05757]Content required.[/]')
            return
        self.dismiss({'name': stem, 'content': content})
