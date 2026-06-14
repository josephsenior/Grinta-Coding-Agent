"""Dialog classes extracted from backend.cli.tui.app.

Pure code motion: class bodies are byte-identical to the
pre-split version. ConfirmWidget and the Grinta*Dialog classes
are self-contained Textual widgets/dialogs.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Label,
    Select,
    Static,
    TextArea,
)

from backend.cli.config_manager import AppConfig
from backend.cli.theme import (
    NAVY_ERROR,
    NAVY_READY,
    NAVY_TEXT_DIM,
    NAVY_TEXT_MUTED,
)
from backend.cli.tui.widgets.dialogs import ModalDialog


class ConfirmWidget(Widget):
    """Inline confirmation bar that appears when the agent needs approval.

    Renders as a single compact row inside the main page rather than
    a blocking modal overlay.
    """

    DEFAULT_CSS = """
    ConfirmWidget {
        height: auto;
        background: #07101d;
        border-top: solid #26324f;
        border-bottom: solid #26324f;
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
        background: #2563eb;
        color: #ffffff;
    }
    ConfirmWidget Button.-default {
        background: #1e293b;
        color: #94a3b8;
    }
    ConfirmWidget .confirm-label {
        color: #64748b;
    }
    ConfirmWidget .confirm-type {
        color: #7dd3fc;
    }
    ConfirmWidget .confirm-target {
        color: #e2e8f0;
        text-style: italic;
    }
    ConfirmWidget .confirm-risk-low {
        color: #4ade80;
    }
    ConfirmWidget .confirm-risk-medium {
        color: #fbbf24;
    }
    ConfirmWidget .confirm-risk-high {
        color: #f87171;
    }
    ConfirmWidget .confirm-risk-unknown {
        color: #94a3b8;
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


class GrintaAddMCPDialog(ModalDialog[dict[str, str] | None]):
    """Dialog to add an MCP Server."""

    BINDINGS = [
        *ModalDialog.BINDINGS,
        Binding('ctrl+s', 'save', 'Save', show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id='dialog-container'):
            yield Label('Add MCP Server', id='dialog-title')
            yield Label('Server Name', classes='field-label')
            yield Input(id='mcp-name')
            yield Label(
                'Command or URL (e.g. npx -y @modelcontextprotocol/server-postgres)',
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


class GrintaSettingsDialog(ModalDialog[dict[str, Any] | None]):
    """Native settings modal for full-screen TUI."""

    DEFAULT_CSS = """
    GrintaSettingsDialog > #dialog-container {
        padding: 1 3;
        height: auto;
        max-height: 92%;
    }
    GrintaSettingsDialog #dialog-title {
        margin-bottom: 0;
    }
    GrintaSettingsDialog .field-label {
        margin-top: 0;
    }
    GrintaSettingsDialog #settings-current-key {
        margin-top: 0;
        margin-bottom: 1;
    }
    GrintaSettingsDialog #settings-provider,
    GrintaSettingsDialog #settings-model,
    GrintaSettingsDialog #settings-reasoning,
    GrintaSettingsDialog #settings-custom-model,
    GrintaSettingsDialog #settings-api-key {
        height: 3;
        margin-bottom: 0;
    }
    GrintaSettingsDialog #settings-model-meta {
        height: auto;
        max-height: 2;
        margin-bottom: 0;
    }
    GrintaSettingsDialog #dialog-feedback {
        margin-top: 0;
        height: 1;
    }
    GrintaSettingsDialog #dialog-buttons {
        margin-top: 1;
    }
    """

    BINDINGS = [
        *ModalDialog.BINDINGS,
        Binding('ctrl+s', 'save', 'Save', show=False),
    ]

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self._config = config
        self._entries_by_provider = self._load_catalog_entries(config)
        self._selected_model_value: str | None = None
        self._selected_provider_value: str | None = None
        self._model_list_request_id = 0

    def _fetch_model_entries_for_provider(self, provider: str) -> dict[str, list[Any]]:
        from backend.inference.registry import build_model_entries_by_provider

        return build_model_entries_by_provider(provider=provider)

    def _apply_model_list_to_ui(self, provider: str) -> None:
        model_select = self.query_one('#settings-model', Select)
        options = self._model_options(provider)
        values = {value for _label, value in options}
        model = self._current_model_for_provider(provider)
        if model not in values:
            model = options[0][1] if options else '__custom__'
        model_select.set_options(options)
        model_select.value = model
        self._selected_model_value = model
        self.query_one(
            '#settings-custom-model', Input
        ).value = self._current_custom_model_for_provider(provider)
        self._sync_custom_model_visibility()
        self._sync_reasoning_options(provider, model)
        self._sync_model_metadata()

    @work(exclusive=True)
    async def _refresh_model_entries_async(self, provider: str | None = None) -> None:
        selected = provider or self._current_provider()
        request_id = self._model_list_request_id
        if not self.is_mounted:
            return
        self._set_feedback(f'Loading {self._provider_label(selected)} models...')
        try:
            merged = await asyncio.to_thread(
                self._fetch_model_entries_for_provider, selected
            )
        except Exception:
            if request_id == self._model_list_request_id and self.is_mounted:
                self._set_feedback(
                    'Could not refresh models; catalog/custom still available.',
                    error=True,
                )
            return
        if request_id != self._model_list_request_id or not self.is_mounted:
            return
        self._entries_by_provider.update(merged)
        self._apply_model_list_to_ui(selected)
        self._set_feedback('')

    def _load_catalog_entries_for_provider(self, provider: str) -> None:
        from backend.inference.registry import build_model_entries_by_provider

        self._entries_by_provider.update(
            build_model_entries_by_provider(provider=provider)
        )

    def _schedule_model_refresh(self, provider: str | None = None) -> None:
        self._model_list_request_id += 1
        self._refresh_model_entries_async(provider)

    def compose(self) -> ComposeResult:
        from backend.cli.config_manager import get_masked_api_key

        current_provider = self._current_provider()
        current_model = self._current_model_for_provider(current_provider)
        current_custom_model = self._current_custom_model_for_provider(current_provider)
        current_reasoning = self._current_reasoning_for_model(
            current_provider, current_model
        )
        masked_key = get_masked_api_key(self._config, current_provider)

        with Vertical(id='dialog-container'):
            yield Label('Settings', id='dialog-title')
            yield Label(
                f'Current {self._provider_label(current_provider)} API key: {masked_key}',
                id='settings-current-key',
            )
            yield Label('Provider', classes='field-label')
            yield Select(
                options=self._provider_options(),
                value=current_provider,
                allow_blank=False,
                id='settings-provider',
            )
            yield Label('Model', classes='field-label')
            yield Select(
                options=self._model_options(current_provider),
                value=current_model,
                allow_blank=False,
                id='settings-model',
            )
            yield Label(
                'Custom model id',
                classes='field-label',
                id='settings-custom-model-label',
            )
            yield Input(value=current_custom_model, id='settings-custom-model')
            yield Label('', id='settings-model-meta')
            yield Label('Reasoning effort', classes='field-label', id='settings-reasoning-label')
            yield Select(
                options=self._reasoning_options(current_provider, current_model),
                value=current_reasoning,
                allow_blank=False,
                id='settings-reasoning',
            )
            yield Label('API key (blank = keep current)', classes='field-label')
            yield Input(password=True, id='settings-api-key')
            yield Label('', id='dialog-feedback')
            with Horizontal(id='dialog-buttons'):
                yield Button('Save', id='settings-save', variant='primary')
                yield Button('Cancel', id='settings-cancel')

    def on_mount(self) -> None:
        self.query_one('#settings-provider', Select).focus()
        provider = self._current_provider()
        self._selected_provider_value = provider
        self._apply_model_list_to_ui(provider)
        self._schedule_model_refresh(provider)

    def action_save(self) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'settings-save':
            self._submit()
            return
        if event.button.id == 'settings-cancel':
            self.dismiss(None)

    def _set_feedback(self, message: str, *, error: bool = False) -> None:
        style = NAVY_ERROR if error else NAVY_READY
        self.query_one('#dialog-feedback', Label).update(f'[{style}]{message}[/]')

    def on_select_changed(self, event: Select.Changed) -> None:
        if not isinstance(event.value, str):
            return
        if event.select.id == 'settings-provider':
            provider = event.value
            self._selected_provider_value = provider
            self._load_catalog_entries_for_provider(provider)
            self._apply_model_list_to_ui(provider)
            self._sync_api_key_label(provider)
            self._schedule_model_refresh(provider)
            return
        if event.select.id == 'settings-model':
            self._selected_model_value = event.value
            provider = self._selected_provider()
            if event.value != '__custom__':
                self.query_one('#settings-custom-model', Input).value = ''
            self._sync_custom_model_visibility()
            self._sync_reasoning_options(provider, event.value)
            self._sync_model_metadata()

    @staticmethod
    def _load_catalog_entries(config: AppConfig) -> dict[str, list[Any]]:
        from backend.cli.config_manager import get_current_provider
        from backend.inference.registry import (
            build_model_entries_by_provider,
            get_listable_providers,
        )

        by_provider: dict[str, list[Any]] = {
            provider: [] for provider in get_listable_providers()
        }
        current = get_current_provider(config)
        if current:
            by_provider.update(
                build_model_entries_by_provider(provider=current)
            )
        return by_provider

    @staticmethod
    def _provider_label(provider: str | None) -> str:
        from backend.inference.registry import provider_label

        return provider_label(provider)

    @staticmethod
    def _entry_label(entry: Any) -> str:
        metadata = getattr(entry, 'metadata', None) or {}
        label = str(metadata.get('display_name') or entry.name)
        return label

    def _provider_options(self) -> list[tuple[str, str]]:
        return [
            (self._provider_label(provider), provider)
            for provider in self._entries_by_provider
        ]

    def _model_options(self, provider: str | None) -> list[tuple[str, str]]:
        entries = self._entries_by_provider.get(provider or '', [])
        options: list[tuple[str, str]] = []
        for entry in entries:
            label = self._entry_label(entry)
            if label != entry.name:
                label = f'{label} ({entry.name})'
            options.append((label, entry.name))
        if options:
            options.append(('Custom model id', '__custom__'))
            return options
        from backend.inference.registry import empty_model_picker_hint

        hint = empty_model_picker_hint(provider)
        return [(hint, '__custom__')]

    def _current_provider(self) -> str:
        from backend.cli.config_manager import get_current_provider

        provider = get_current_provider(self._config)
        if provider in self._entries_by_provider:
            return provider
        return next(iter(self._entries_by_provider), 'openai')

    def _current_model_for_provider(self, provider: str | None) -> str:
        from backend.inference.catalog_loader import (
            lookup_provider_model,
            runtime_model_id,
        )

        entries = self._entries_by_provider.get(provider or '', [])
        if not entries:
            return '__custom__'
        try:
            model = (self._config.get_llm_config().model or '').strip()
            bare = model.split('/', 1)[1] if model.startswith(f'{provider}/') else model
            entry = lookup_provider_model(provider, bare, allow_aliases=True)
            if entry is not None:
                return entry.name
            for candidate in entries:
                if bare in {candidate.name, runtime_model_id(candidate)}:
                    return candidate.name
            if bare:
                return '__custom__'
        except Exception:
            pass
        return '__custom__' if not entries else entries[0].name

    def _current_custom_model_for_provider(self, provider: str | None) -> str:
        try:
            model = (self._config.get_llm_config().model or '').strip()
        except Exception:
            return ''
        provider = (provider or '').strip()
        if provider and model.startswith(f'{provider}/'):
            return model.split('/', 1)[1]
        from backend.inference.provider_resolver import extract_provider_prefix

        prefixed = extract_provider_prefix(model)
        if prefixed == provider:
            return model.split('/', 1)[1]
        return (
            model if self._current_model_for_provider(provider) == '__custom__' else ''
        )

    def _selected_provider(self) -> str:
        value = self.query_one('#settings-provider', Select).value
        if isinstance(value, str) and value:
            return value
        if self._selected_provider_value:
            return self._selected_provider_value
        return self._current_provider()

    def _selected_model(self) -> str:
        value = self.query_one('#settings-model', Select).value
        if isinstance(value, str) and value:
            return value
        if self._selected_model_value:
            return self._selected_model_value
        return self._current_model_for_provider(self._selected_provider())

    def _selected_entry(self, provider: str | None, model: str | None):
        from backend.inference.param_profiles import (
            resolve_model_entry_for_capabilities,
        )

        if model == '__custom__' or not model:
            return None

        fallback = None
        for candidate in self._entries_by_provider.get(provider or '', []):
            if candidate.name == model:
                fallback = candidate
                break

        return resolve_model_entry_for_capabilities(
            model,
            provider,
            fallback=fallback,
        )

    def _custom_model_enabled(self) -> bool:
        return self._selected_model() == '__custom__'

    def _sync_custom_model_visibility(self) -> None:
        enabled = self._custom_model_enabled()
        try:
            self.query_one('#settings-custom-model-label', Label).display = enabled
            self.query_one('#settings-custom-model', Input).display = enabled
        except Exception:
            pass

    def _reasoning_options(
        self, provider: str | None, model: str | None
    ) -> list[tuple[str, str]]:
        from backend.inference.reasoning import reasoning_effort_display_options

        entry = self._selected_entry(provider, model)
        if entry is None:
            return [('Default', '')]
        options = reasoning_effort_display_options(entry, include_disabled=True)
        if not options:
            return [('Not supported by selected model', '')]
        return options

    def _current_reasoning_for_model(self, provider: str, model: str) -> str:
        configured = ''
        try:
            configured = (
                (getattr(self._config.get_llm_config(), 'reasoning_effort', None) or '')
                .strip()
                .lower()
            )
        except Exception:
            configured = ''
        allowed = {value for _label, value in self._reasoning_options(provider, model)}
        return configured if configured in allowed else ''

    def _sync_reasoning_options(self, provider: str, model: str) -> None:
        from backend.inference.reasoning import reasoning_control_label

        entry = self._selected_entry(provider, model)
        self.query_one('#settings-reasoning-label', Label).update(
            reasoning_control_label(entry)
        )
        select = self.query_one('#settings-reasoning', Select)
        options = self._reasoning_options(provider, model)
        select.set_options(options)
        values = {value for _label, value in options}
        current = self._current_reasoning_for_model(provider, model)
        select.value = current if current in values else ''

    def _sync_api_key_label(self, provider: str) -> None:
        from backend.cli.config_manager import get_masked_api_key

        masked = get_masked_api_key(self._config, provider)
        self.query_one('#settings-current-key', Label).update(
            f'Current {self._provider_label(provider)} API key: {masked}'
        )

    def _sync_model_metadata(self) -> None:
        provider = self._selected_provider()
        model = self._selected_model()
        entry = self._selected_entry(provider, model)
        if entry is None:
            if self._custom_model_enabled():
                from backend.inference.registry import empty_model_picker_hint

                self.query_one('#settings-model-meta', Label).update(
                    f'[{NAVY_TEXT_MUTED}]{empty_model_picker_hint(provider)}[/]'
                )
            else:
                self.query_one('#settings-model-meta', Label).update('')
            return
        context = getattr(entry, 'context_window_tokens', None)
        output = getattr(entry, 'max_output_tokens', None)
        tools = (
            'tools'
            if getattr(entry, 'supports_function_calling', False)
            else 'no tools'
        )
        parallel = (
            'parallel tools'
            if getattr(entry, 'supports_parallel_tool_calls', False)
            else 'serial tools'
        )
        details = [tools, parallel]
        if context:
            details.append(f'context {context:,}')
        if output:
            details.append(f'output {output:,}')
        self.query_one('#settings-model-meta', Label).update(
            f'[{NAVY_TEXT_MUTED}]{" | ".join(details)}[/]'
        )

    def _resolve_submit_model(self) -> str:
        """Read the model id the user chose, including Textual Select edge cases."""
        model_select = self.query_one('#settings-model', Select)
        selected = ''
        for candidate in (
            model_select.value,
            getattr(model_select, 'selection', None),
            self._selected_model_value,
        ):
            if isinstance(candidate, str) and candidate:
                selected = candidate
                break
        if not selected:
            selected = self._current_model_for_provider(self._selected_provider())

        custom_model = self.query_one('#settings-custom-model', Input).value.strip()
        if selected == '__custom__':
            return custom_model
        return selected

    def _submit(self) -> None:
        from backend.inference.catalog_loader import runtime_model_id

        provider = self._selected_provider()
        model = self._resolve_submit_model()
        entry = self._selected_entry(provider, model)
        reasoning_value = self.query_one('#settings-reasoning', Select).value
        reasoning = reasoning_value if isinstance(reasoning_value, str) else ''
        api_key = self.query_one('#settings-api-key', Input).value.strip()

        if not provider:
            self._set_feedback('Provider is required.', error=True)
            return
        if not model:
            self._set_feedback('Model is required.', error=True)
            return

        runtime_model = runtime_model_id(entry) if entry is not None else model
        self.dismiss(
            {
                'provider': provider,
                'model': runtime_model,
                'reasoning_effort': reasoning,
                'api_key': api_key,
            }
        )


class GrintaSessionsDialog(ModalDialog[str | None]):
    """Native sessions manager for full-screen TUI."""

    DEFAULT_CSS = """
    GrintaSessionsDialog > #dialog-container {
        max-height: 40;
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
        self._all_entries: list[tuple[str, dict[str, Any], int]] = []
        self._visible_entries: list[tuple[str, dict[str, Any], int]] = []
        self._sessions_root: Path | None = None

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
            with Horizontal(id='sessions-filters'):
                yield Input(
                    value=self._search, placeholder='Search…', id='sessions-search'
                )
                yield Select(
                    options=options,
                    value=self._sort_by,
                    allow_blank=False,
                    id='sessions-sort',
                )
                yield Input(
                    value=str(self._limit), restrict=r'\d*', id='sessions-limit'
                )
                yield Button('Refresh', id='sessions-refresh')
            yield DataTable(id='sessions-table')
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

    def _set_feedback(self, message: str, *, error: bool = False) -> None:
        style = NAVY_ERROR if error else NAVY_READY
        self.query_one('#dialog-feedback', Label).update(f'[{style}]{message}[/]')

    def _refresh_table(self) -> None:
        from backend.cli.session_manager import (
            _filter_sessions_fuzzy,
            _find_sessions_root,
            _list_session_entries,
        )

        self._sessions_root = _find_sessions_root(self._config)
        table = self.query_one('#sessions-table', DataTable)
        table.clear()
        if self._sessions_root is None:
            self._all_entries = []
            self._visible_entries = []
            self._set_feedback('No session storage found.', error=True)
            self.query_one('#sessions-preview', Static).update('')
            return

        entries = _list_session_entries(self._sessions_root, sort_by=self._sort_by)
        self._all_entries = entries
        if self._search:
            entries = _filter_sessions_fuzzy(entries, self._search)
        self._visible_entries = entries[: self._limit]
        for i, (sid, meta, event_count) in enumerate(self._visible_entries, 1):
            title = str(meta.get('title') or meta.get('name') or '—')
            updated = str(meta.get('last_updated_at') or meta.get('created_at') or '—')[
                :19
            ]
            table.add_row(str(i), sid[:12], title, str(event_count), updated, key=sid)

        if self._visible_entries:
            table.move_cursor(row=0, column=0, animate=False, scroll=False)
            self._update_preview(0)
            self._set_feedback(f'{len(self._visible_entries)} session(s) loaded.')
        else:
            self.query_one('#sessions-preview', Static).update('')
            if self._search:
                self._set_feedback(
                    f'No sessions matching "{self._search}".', error=True
                )
            else:
                self._set_feedback('No sessions found.', error=True)

    def _select_target(self, target: str) -> None:
        from backend.cli.session_manager import _resolve_target

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
        sid, meta, event_count = self._visible_entries[row_index]
        lines = self._build_preview_lines(sid, meta, event_count)
        self.query_one('#sessions-preview', Static).update('\n'.join(lines))

    def _delete_sessions(self, targets: list[str]) -> tuple[int, list[str]]:
        from backend.cli.session_manager import _resolve_target

        if self._sessions_root is None:
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
                shutil.rmtree(self._sessions_root / sid, ignore_errors=False)
                deleted += 1
            except Exception as exc:
                errors.append(f'{sid[:12]}: {exc}')
        return deleted, errors
