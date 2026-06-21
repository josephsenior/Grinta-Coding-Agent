"""Confirm bar and modal confirmation dialogs."""

from __future__ import annotations

import asyncio
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, Label, Static

from backend.cli.tui.widgets.dialogs import ModalDialog


class ConfirmWidget(Widget):
    """Inline confirmation bar that appears when the agent needs approval.

    Renders as a single compact row inside the main page rather than
    a blocking modal overlay.
    """

    DEFAULT_CSS = """
    ConfirmWidget {
        height: auto;
        background: #08101d;
        border-top: solid #1b233a;
        border-bottom: solid #1b233a;
        border-left: heavy #5eead4;
        padding: 1 1 0 1;
        display: none;
    }
    ConfirmWidget.-visible {
        display: block;
    }
    ConfirmWidget #confirm-bar {
        layout: horizontal;
        height: 3;
        align: left middle;
    }
    ConfirmWidget #confirm-info {
        width: 1fr;
        height: 3;
        color: #cbd5e1;
        padding: 0 1 0 0;
        content-align: left middle;
    }
    ConfirmWidget #confirm-actions {
        width: auto;
        height: 3;
        align: right middle;
        margin-left: 1;
    }
    ConfirmWidget #confirm-actions Button {
        margin-left: 1;
    }
    ConfirmWidget Button.-primary {
        background: #1e3a70;
        color: #ffffff;
    }
    ConfirmWidget Button.-default {
        background: #101c36;
        color: #8f9fc1;
    }
    ConfirmWidget .confirm-label {
        color: #8f9fc1;
    }
    ConfirmWidget .confirm-type {
        color: #91abec;
    }
    ConfirmWidget .confirm-target {
        color: #e2e8f0;
        text-style: italic;
    }
    ConfirmWidget .confirm-risk-low {
        color: #54efae;
    }
    ConfirmWidget .confirm-risk-medium {
        color: #f6ff8f;
    }
    ConfirmWidget .confirm-risk-high {
        color: #fd8383;
    }
    ConfirmWidget .confirm-risk-unknown {
        color: #969aad;
    }
    """

    _ACTION_VERBS: dict[str, str] = {
        'Run Command': 'execute',
        'Edit File': 'edit',
        'Write File': 'write',
        'Read File': 'read',
        'MCP Tool': 'use',
        'Browser': 'use',
        'Delegate': 'delegate',
    }

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._decision_event: asyncio.Event = asyncio.Event()
        self._decision: str | None = None
        self._options: list[tuple[str, str]] = []
        self._recommended: int | None = None
        self._button_render_count = 0
        self._button_id_to_key: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        with Horizontal(id='confirm-bar'):
            yield Static('', id='confirm-info')
            with Horizontal(id='confirm-actions'):
                pass

    def configure(
        self,
        action_type: str,
        risk_label: str,
        risk_class: str,
        target: str,
        options: list[tuple[str, str]],
        recommended: int | None = None,
    ) -> None:
        """Populate the confirmation bar with action details."""
        verb = self._ACTION_VERBS.get(action_type, action_type.lower())
        if target:
            truncated = target if len(target) <= 72 else target[:69] + '...'
            info = (
                f'[dim]Agent wants to {verb}[/] '
                f'[white]{truncated}[/] '
                f'[{risk_class}]({risk_label} risk)[/]'
            )
        else:
            info = f'[dim]Agent wants to {verb}[/] [{risk_class}]({risk_label} risk)[/]'

        info_static = self.query_one('#confirm-info', Static)
        info_static.update(info)

        actions = self.query_one('#confirm-actions', Horizontal)
        actions.remove_children()
        self._options = options
        self._recommended = recommended
        self._button_render_count += 1
        self._button_id_to_key = {}
        for i, (key, label) in enumerate(options):
            button_id = f'confirm-{key}-{self._button_render_count}'
            self._button_id_to_key[button_id] = key
            btn = Button(
                label,
                id=button_id,
                variant='primary' if i == (recommended or 0) else 'default',
            )
            actions.mount(btn)

    def configure_prompt(
        self,
        message: str,
        options: list[tuple[str, str]],
        recommended: int | None = None,
    ) -> None:
        """Populate the confirmation bar with a simple prompt."""
        info_static = self.query_one('#confirm-info', Static)
        info_static.update(message)

        actions = self.query_one('#confirm-actions', Horizontal)
        actions.remove_children()
        self._options = options
        self._recommended = recommended
        self._button_render_count += 1
        self._button_id_to_key = {}
        for i, (key, label) in enumerate(options):
            button_id = f'confirm-{key}-{self._button_render_count}'
            self._button_id_to_key[button_id] = key
            btn = Button(
                label,
                id=button_id,
                variant='primary' if i == (recommended or 0) else 'default',
            )
            actions.mount(btn)

    def show(self) -> None:
        self.add_class('-visible')
        self._decision = None
        self._decision_event.clear()

    def hide(self) -> None:
        self.remove_class('-visible')

    async def wait_for_decision(self) -> str | None:
        """Block until the user clicks a button."""
        await self._decision_event.wait()
        return self._decision

    def on_button_pressed(self, event: Button.Pressed) -> None:
        key = self._button_id_to_key.get(str(event.button.id or ''))
        if key is None:
            return
        self._decision = key
        self._decision_event.set()
        self.hide()


class GrintaConfirmDialog(ModalDialog[str | None]):
    """Modal confirmation dialog for one-off confirmations."""

    DEFAULT_CSS = """
    GrintaConfirmDialog > #dialog-container {
        width: 50;
    }
    """

    def __init__(
        self,
        title: str,
        body: str,
        options: list[tuple[str, str]],
        recommended: int | None = None,
    ) -> None:
        super().__init__()
        self._dialog_title = title
        self._dialog_body = body
        self._options = options
        self._recommended = recommended

    def compose(self) -> ComposeResult:
        with Vertical(id='dialog-container'):
            yield Label(self._dialog_title, id='dialog-title')
            yield Static(self._dialog_body, id='dialog-body')
            with Horizontal(id='dialog-buttons'):
                for i, (key, label) in enumerate(self._options):
                    yield Button(
                        label,
                        id=f'confirm-{key}',
                        variant='primary'
                        if i == (self._recommended or 0)
                        else 'default',
                    )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        for key, _label in self._options:
            if event.button.id == f'confirm-{key}':
                self.dismiss(key)
                return
