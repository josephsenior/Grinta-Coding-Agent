"""Settings screen — configure LLM model, API key, and confirmation mode."""

from __future__ import annotations

import logging
from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
    Switch,
)

from tui.client import ForgeClient

logger = logging.getLogger("forge.tui.settings")


class SettingsScreen(Screen[None]):
    """Settings editor for LLM configuration and secrets.

    Loads current settings from the API, lets the user edit, and saves back.
    """

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True),
        Binding("ctrl+s", "save", "Save", show=True),
    ]

    def __init__(self, client: ForgeClient) -> None:
        super().__init__()
        self.client = client
        self._settings: dict[str, Any] = {}
        self._models: list[dict[str, Any]] = []
        self._models_ready: bool = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="settings-outer"):
            yield Static("⚙  Settings", classes="section-title")
            with VerticalScroll(id="settings-scroll"):
                # LLM Configuration
                with Vertical(classes="section"):
                    yield Static("LLM Configuration", classes="section-title")
                    with Horizontal(classes="field-row"):
                        yield Label("Model", classes="field-label")
                        yield Select[str](
                            [("Loading…", "__loading__")],
                            id="model-select",
                            prompt="Select a model…",
                            allow_blank=True,
                            classes="field-input",
                        )
                    with Horizontal(classes="field-row"):
                        yield Label("API Key", classes="field-label")
                        yield Input(
                            placeholder="sk-…",
                            id="api-key-input",
                            password=True,
                            classes="field-input",
                        )

                # Agent Behaviour
                with Vertical(classes="section"):
                    yield Static("Agent Behaviour", classes="section-title")
                    with Horizontal(classes="field-row"):
                        yield Label("Confirmation Mode", classes="field-label")
                        yield Switch(id="confirmation-switch")
                    with Horizontal(classes="field-row"):
                        yield Label("Max Iterations", classes="field-label")
                        yield Input(
                            placeholder="100",
                            id="max-iterations-input",
                            classes="field-input",
                        )

                # Secret Management
                with Vertical(classes="section"):
                    yield Static("Secrets", classes="section-title")
                    with Horizontal(classes="field-row"):
                        yield Label("Provider", classes="field-label")
                        yield Input(
                            placeholder="e.g. github, custom",
                            id="secret-provider-input",
                            classes="field-input",
                        )
                    with Horizontal(classes="field-row"):
                        yield Label("Token", classes="field-label")
                        yield Input(
                            placeholder="token value",
                            id="secret-token-input",
                            password=True,
                            classes="field-input",
                        )
                    yield Button("Set Secret", id="btn-set-secret", variant="primary")

                with Horizontal(id="btn-row"):
                    yield Button("Save Settings", id="btn-save", variant="success")
                    yield Button("Cancel", id="btn-cancel", variant="default")

        yield Footer()

    async def on_mount(self) -> None:
        """Load current settings and populate fields."""
        await self._load_settings()
        await self._load_models()

    async def _load_settings(self) -> None:
        try:
            self._settings = await self.client.get_settings()
        except Exception as e:
            self.notify(f"Failed to load settings: {e}", severity="error")
            return

        # Safely extract nested values using a helper
        def safe_get(d, *keys, default=None):
            """Safely traverse nested dicts, returning default if path invalid."""
            if not isinstance(d, dict):
                return default
            for key in keys:
                d = d.get(key, {})
                if not isinstance(d, dict) and key != keys[-1]:
                    return default
            return d if d else default

        llm_data = safe_get(self._settings, "llm", default={})
        api_key = str(
            self._settings.get("llm_api_key")
            or (llm_data.get("api_key") if isinstance(llm_data, dict) else None)
            or self._settings.get("api_key")
            or ""
        )
        security = safe_get(self._settings, "security", default={})
        confirmation = bool(
            self._settings.get("confirmation_mode")
            or (
                security.get("confirmation_mode")
                if isinstance(security, dict)
                else False
            )
            or False
        )
        agent = safe_get(self._settings, "agent", default={})
        max_iter = str(
            self._settings.get("max_iterations")
            or (agent.get("max_iterations") if isinstance(agent, dict) else None)
            or 100
        )

        if api_key:
            self.query_one("#api-key-input", Input).value = api_key
        elif self._settings.get("llm_api_key_set"):
            self.query_one("#api-key-input", Input).value = "**********"
        self.query_one("#confirmation-switch", Switch).value = confirmation
        self.query_one("#max-iterations-input", Input).value = max_iter

    async def _load_models(self) -> None:
        try:
            self._models = await self.client.get_models()
            if not self._models:
                logger.warning("get_models returned empty list")
        except Exception as e:
            logger.error(f"Failed to load models: {e}")
            self.notify(f"Warning: Could not load models: {e}", severity="warning")
            return

        select = self.query_one("#model-select", Select)
        options: list[tuple[str, str]] = []
        for m in self._models:
            model_id = str(m.get("id", m.get("model", str(m))))
            name = str(m.get("name", model_id))
            options.append((name, model_id))

        if not options:
            return

        select.set_options(options)
        self._models_ready = True

        # Determine current model (safely handle nested access)
        llm_data = (
            self._settings.get("llm", {})
            if isinstance(self._settings.get("llm"), dict)
            else {}
        )
        current_model = (
            self._settings.get("llm_model")
            or (llm_data.get("model") if isinstance(llm_data, dict) else None)
            or self._settings.get("model")
        )
        if current_model:
            valid_ids = {opt[1] for opt in options}
            if current_model in valid_ids:
                select.value = current_model

    # ── button handlers ───────────────────────────────────────────

    @on(Button.Pressed, "#btn-save")
    async def _save_settings(self) -> None:
        select = self.query_one("#model-select", Select)
        model_val = select.value
        api_key = self.query_one("#api-key-input", Input).value.strip()
        confirmation = self.query_one("#confirmation-switch", Switch).value
        max_iter = self.query_one("#max-iterations-input", Input).value.strip()

        payload: dict[str, Any] = {
            "confirmation_mode": confirmation,
        }

        # Only send model if user actually selected one
        if model_val and model_val != Select.BLANK and model_val != "__loading__":
            payload["llm_model"] = str(model_val)
        if api_key:
            payload["llm_api_key"] = api_key
        if max_iter:
            try:
                payload["max_iterations"] = int(max_iter)
            except ValueError:
                pass

        try:
            await self.client.save_settings(payload)
            self.notify("Settings saved", severity="information")
        except Exception as e:
            self.notify(f"Save failed: {e}", severity="error")

    @on(Button.Pressed, "#btn-cancel")
    def _cancel(self) -> None:
        self.dismiss()

    @on(Button.Pressed, "#btn-set-secret")
    async def _set_secret(self) -> None:
        provider = self.query_one("#secret-provider-input", Input).value.strip()
        token = self.query_one("#secret-token-input", Input).value.strip()
        if not provider or not token:
            self.notify("Provider and token are required", severity="warning")
            return
        try:
            await self.client.set_secret(provider, token)
            self.notify(f"Secret for '{provider}' saved", severity="information")
            self.query_one("#secret-token-input", Input).value = ""
        except Exception as e:
            self.notify(f"Failed: {e}", severity="error")

    # ── key bindings ──────────────────────────────────────────────

    def action_go_back(self) -> None:
        self.dismiss()

    async def action_save(self) -> None:
        await self._save_settings()
