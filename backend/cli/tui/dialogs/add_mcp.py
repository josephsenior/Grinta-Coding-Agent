"""Add MCP server dialog."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, Static

from backend.cli.tui.widgets.dialogs import ModalDialog


class GrintaAddMCPDialog(ModalDialog[dict[str, str] | None]):
    """Dialog to add an MCP Server."""

    BINDINGS = [
        *ModalDialog.BINDINGS,
        Binding('ctrl+s', 'save', 'Save', show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id='dialog-container'):
            yield Label('Add MCP Server', id='dialog-title')
            yield Static(
                'Register a local command or remote endpoint for tool access.',
                id='dialog-subtitle',
            )
            yield Label('Server name', classes='field-label')
            yield Input(id='mcp-name')
            yield Label(
                'Command or HTTPS URL',
                classes='field-label',
            )
            yield Input(id='mcp-command')
            yield Label('', id='dialog-feedback')
            with Horizontal(id='dialog-buttons'):
                yield Button('Save', id='settings-save', variant='primary')
                yield Button('Cancel', id='settings-cancel')

    def on_mount(self) -> None:
        self.query_one('#mcp-name', Input).focus()

    def action_save(self) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'settings-save':
            self._submit()
        elif event.button.id == 'settings-cancel':
            self.dismiss(None)

    def _submit(self) -> None:
        name = self.query_one('#mcp-name', Input).value.strip()
        cmd = self.query_one('#mcp-command', Input).value.strip()
        if not name or not cmd:
            self.query_one('#dialog-feedback', Label).update(
                '[#f05757]Name and command required.[/]'
            )
            return
        self.dismiss({'name': name, 'command': cmd})
