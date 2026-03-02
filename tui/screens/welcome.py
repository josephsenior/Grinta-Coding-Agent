"""Welcome screen — first-run onboarding wizard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.screen import Screen
from textual.widgets import Button, Input, Label, RadioButton, RadioSet, Static

class WelcomeScreen(Screen[bool]):
    """Onboarding wizard for first-time users."""

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static("🚀 Welcome to Forge", id="welcome-title"),
            Static(
                "Forge is a local-first AI coding agent. Let's get you set up in 30 seconds.",
                id="welcome-subtitle"
            ),
            Vertical(
                Label("1. Choose your primary LLM provider:"),
                RadioSet(
                    RadioButton("OpenAI (GPT-4o)", value=True, id="provider-openai"),
                    RadioButton("Anthropic (Claude 3.5 Sonnet)", id="provider-anthropic"),
                    RadioButton("Local (Ollama / OpenRouter)", id="provider-local"),
                    id="llm-provider"
                ),
                classes="setup-step"
            ),
            Vertical(
                Label("2. Enter your API Key:"),
                Input(placeholder="sk-...", password=True, id="api-key-input"),
                Static("Leave blank for local models.", classes="help-text"),
                classes="setup-step"
            ),
            Vertical(
                Label("3. Workspace Directory (where your code lives):"),
                Horizontal(
                    Input(value=str(Path.cwd() / "workspace"), id="workspace-input"),
                    classes="input-row"
                ),
                classes="setup-step"
            ),
            Horizontal(
                Button("Finish Setup", variant="success", id="btn-finish"),
                id="welcome-actions"
            ),
            id="welcome-container"
        )

    def on_mount(self) -> None:
        self.query_one("#api-key-input").focus()

    @on(Button.Pressed, "#btn-finish")
    def finish_setup(self) -> None:
        """Save config and dismiss."""
        provider = "openai"
        anth_radio = cast(RadioButton, self.query_one("#provider-anthropic"))
        local_radio = cast(RadioButton, self.query_one("#provider-local"))
        api_key_input = cast(Input, self.query_one("#api-key-input"))
        workspace_input = cast(Input, self.query_one("#workspace-input"))
        if anth_radio.value:
            provider = "anthropic"
        elif local_radio.value:
            provider = "local"

        api_key = api_key_input.value.strip()
        workspace = workspace_input.value.strip()

        # Generate settings.json
        self._save_config(provider, api_key, workspace)
        self.dismiss(True)

    def _save_config(self, provider: str, api_key: str, workspace: str) -> None:
        settings_path = Path.cwd() / "settings.json"

        # Start with defaults (flat format for load_from_json compatibility)
        config_data: dict[str, Any] = {
            "workspace_base": workspace,
            "max_budget_per_task": 5.0,
            "llm_model": "gpt-4o" if provider == "openai" else "claude-3-5-sonnet-20240620" if provider == "anthropic" else "ollama/llama3.2",
            "llm_api_key": api_key,
            "llm_base_url": "",
            "model_aliases": {},
        }

        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2)
        
        # Create workspace dir if missing
        w_path = Path(workspace)
        if not w_path.exists():
            try:
                w_path.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
