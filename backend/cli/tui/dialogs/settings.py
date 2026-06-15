"""LLM provider/model settings dialog."""

from __future__ import annotations

import asyncio
from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, Select

from backend.core.config import AppConfig
from backend.cli.theme import NAVY_ERROR, NAVY_READY, NAVY_TEXT_MUTED
from backend.cli.tui.widgets.dialogs import ModalDialog

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
        from backend.cli.settings import get_masked_api_key

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
        from backend.cli.settings import get_current_provider
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
        from backend.cli.settings import get_current_provider

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
        from backend.cli.settings import get_masked_api_key

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

