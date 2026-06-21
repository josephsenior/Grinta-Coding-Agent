"""Add or edit MCP server dialog."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, Static

from backend.cli.tui.widgets.dialogs import ModalDialog


class GrintaAddMCPDialog(ModalDialog[dict[str, str] | None]):
    """Dialog to add or edit an MCP server."""

    BINDINGS = [
        *ModalDialog.BINDINGS,
        Binding('ctrl+s', 'save', 'Save', show=False),
    ]

    def __init__(
        self,
        existing_names: set[str] | None = None,
        *,
        edit_name: str | None = None,
        edit_command: str | None = None,
    ) -> None:
        super().__init__()
        self._existing_names = {name.lower() for name in (existing_names or set())}
        self._edit_name = (edit_name or '').strip() or None
        self._edit_command = edit_command

    def compose(self) -> ComposeResult:
        title = 'Edit MCP Server' if self._edit_name else 'Add MCP Server'
        with Vertical(id='dialog-container'):
            yield Label(title, id='dialog-title')
            yield Static(
                'Register a local command or remote endpoint for tool access.',
                id='dialog-subtitle',
            )
            yield Label('Server name', classes='field-label')
            yield Input(id='mcp-name', placeholder='github')
            yield Label(
                'Command or HTTPS URL',
                classes='field-label',
            )
            yield Input(
                id='mcp-command',
                placeholder='npx -y @modelcontextprotocol/server-github',
            )
            yield Static('[#54597b]stdio or sse[/]', id='mcp-type-hint')
            yield Label('', id='dialog-feedback')
            with Horizontal(id='dialog-buttons'):
                yield Button('Save', id='settings-save', variant='primary')
                yield Button('Cancel', id='settings-cancel')

    def on_mount(self) -> None:
        name_input = self.query_one('#mcp-name', Input)
        command_input = self.query_one('#mcp-command', Input)
        if self._edit_name:
            name_input.value = self._edit_name
            name_input.disabled = True
            if self._edit_command:
                command_input.value = self._edit_command
                self._update_mcp_type_hint(self._edit_command)
            command_input.focus()
        else:
            name_input.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == 'mcp-command':
            self._update_mcp_type_hint(event.value)

    def _update_mcp_type_hint(self, value: str) -> None:
        hint = self.query_one('#mcp-type-hint', Static)
        cmd = value.strip()
        if not cmd:
            hint.update('[#54597b]stdio or sse[/]')
        elif cmd.startswith('http://') or cmd.startswith('https://'):
            hint.update('[#54efae]Detected: sse (remote URL)[/]')
        else:
            hint.update('[#54efae]Detected: stdio (local command)[/]')

    def action_save(self) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'settings-save':
            self._submit()
        elif event.button.id == 'settings-cancel':
            self.dismiss(None)

    def _submit(self) -> None:
        feedback = self.query_one('#dialog-feedback', Label)
        name = self.query_one('#mcp-name', Input).value.strip()
        cmd = self.query_one('#mcp-command', Input).value.strip()
        if not name or not cmd:
            feedback.update('[#f05757]Name and command required.[/]')
            return
        if not self._edit_name and name.lower() in self._existing_names:
            feedback.update(f'[#f05757]Server name already exists: {name}[/]')
            return
        self.dismiss({'name': name, 'command': cmd})
