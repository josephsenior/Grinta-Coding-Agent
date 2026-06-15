"""Help and keyboard shortcuts dialog."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Label, Static

from backend.cli.theme import NAVY_TEXT_MUTED
from backend.cli.tui.widgets.dialogs import ModalDialog


class GrintaHelpDialog(ModalDialog[None]):
    """Dedicated help and shortcuts modal."""

    def compose(self) -> ComposeResult:
        from backend.cli.tui.app import GrintaScreen
        from backend.cli.tui.widgets.command_list import (
            KEYBOARD_SHORTCUTS,
            CommandListPanel,
            CommandListRow,
            CommandListSection,
            build_slash_command_rows,
        )

        slash_rows = build_slash_command_rows(GrintaScreen._SLASH_HINTS)
        with Vertical(id='dialog-container'):
            yield Label('Help', id='dialog-title')
            yield Static(
                f'[{NAVY_TEXT_MUTED}]Use the transcript for evidence and the HUD for runtime state.[/]',
                id='dialog-subtitle',
            )
            with Vertical(id='help-body'):
                yield CommandListPanel(
                    rows=slash_rows,
                    section_title='Slash commands',
                    id='help-commands',
                )
                yield CommandListSection('Keyboard shortcuts')
                for key, detail in KEYBOARD_SHORTCUTS:
                    yield CommandListRow(key, detail)
            with Horizontal(id='dialog-buttons'):
                yield Button('Close', id='help-close', variant='primary')

    def on_mount(self) -> None:
        self.query_one('#help-close', Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'help-close':
            self.dismiss(None)
