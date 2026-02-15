"""Settings screen — configure LLM model, API key, and confirmation mode."""

from __future__ import annotations

from typing import Any

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
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

from backend.tui.client import ForgeClient


class SettingsScreen(Screen[None]):
    """Settings editor for LLM configuration and secrets.

    Loads current settings from the API, lets the user edit, and saves back.
    """

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True),
        Binding("ctrl+s", "save", "Save", show=True),
    ]

    CSS = """
    #settings-outer {
        height: 100%;
        padding: 1 2;
        overflow-y: auto;
    }
    .section {
        margin: 1 0;
        padding: 1 2;
        border: round $primary;
        height: auto;
    }
    .section-title {
        text-style: bold;
        color: $accent;
        margin: 0 0 1 0;
    }
    .field-row {
        height: 3;
        margin: 0 0 1 0;
    }
    .field-label {
        width: 24;
        text-style: bold;
        padding: 0 1 0 0;
    }
    .field-input {
        width: 1fr;
    }
    #btn-row {
        height: 3;
        margin: 1 0;
        content-align: center middle;
    }
    """

    def __init__(self, client: ForgeClient) -> None:
        super().__init__()
        self.client = client
        self._settings: dict[str, Any] = {}
        self._models: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="settings-outer"):
            yield Static("⚙  Settings", classes="section-title")

            # LLM Configuration
            with Vertical(classes="section"):
                yield Static("LLM Configuration", classes="section-title")
                with Horizontal(classes="field-row"):
                    yield Label("Model", classes="field-label")
                    yield Select(
                        [],
                        id="model-select",
                        prompt="Select a model…",
                        classes="field-input",
                    )
                with Horizontal(classes="field-row"):
                    yield Label("Custom Model", classes="field-label")
                    yield Input(
                        placeholder="e.g. gpt-4o, claude-sonnet-4-20250514",
                        id="custom-model-input",
                        classes="field-input",
                    )
                with Horizontal(classes="field-row"):
                    yield Label("Base URL", classes="field-label")
                    yield Input(
                        placeholder="https://api.openai.com/v1 (leave blank for default)",
                        id="base-url-input",
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

        # Populate fields
        llm = self._settings.get("llm", self._settings)
        model = llm.get("model", "")
        base_url = llm.get("base_url", llm.get("api_base", ""))
        api_key = llm.get("api_key", "")
        confirmation = self._settings.get("security", {}).get(
            "confirmation_mode", False
        )
        max_iter = str(self._settings.get("agent", {}).get("max_iterations", 100))

        if model:
            self.query_one("#custom-model-input", Input).value = model
        if base_url:
            self.query_one("#base-url-input", Input).value = str(base_url)
        if api_key:
            self.query_one("#api-key-input", Input).value = str(api_key)
        self.query_one("#confirmation-switch", Switch).value = bool(confirmation)
        self.query_one("#max-iterations-input", Input).value = max_iter

    async def _load_models(self) -> None:
        try:
            self._models = await self.client.get_models()
        except Exception:
            return

        select = self.query_one("#model-select", Select)
        options: list[tuple[str, str]] = []
        for m in self._models:
            name = str(m.get("model", m.get("name", str(m))))
            options.append((name, name))
        if options:
            select.set_options(options)

    # ── button handlers ───────────────────────────────────────────

    @on(Button.Pressed, "#btn-save")
    async def _save_settings(self) -> None:
        model = self.query_one("#custom-model-input", Input).value.strip()
        base_url = self.query_one("#base-url-input", Input).value.strip()
        api_key = self.query_one("#api-key-input", Input).value.strip()
        confirmation = self.query_one("#confirmation-switch", Switch).value
        max_iter = self.query_one("#max-iterations-input", Input).value.strip()

        payload: dict[str, Any] = {}

        if model or base_url or api_key:
            llm: dict[str, Any] = {}
            if model:
                llm["model"] = model
            if base_url:
                llm["base_url"] = base_url
            if api_key:
                llm["api_key"] = api_key
            payload["llm"] = llm

        payload["security"] = {"confirmation_mode": confirmation}

        if max_iter:
            try:
                payload.setdefault("agent", {})["max_iterations"] = int(max_iter)
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

    @on(Select.Changed, "#model-select")
    def _on_model_selected(self, event: Select.Changed) -> None:
        if event.value and event.value != Select.BLANK:
            self.query_one("#custom-model-input", Input).value = str(event.value)

    # ── key bindings ──────────────────────────────────────────────

    def action_go_back(self) -> None:
        self.dismiss()

    async def action_save(self) -> None:
        await self._save_settings()
