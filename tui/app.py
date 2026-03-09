"""Forge TUI — main Textual application."""

from __future__ import annotations

import logging
from pathlib import Path

from textual.app import App
from textual.binding import Binding

from tui.client import ForgeClient
from tui.screens.help import HelpScreen
from tui.screens.home import HomeScreen
from tui.screens.welcome import WelcomeScreen

logger = logging.getLogger("forge.tui")

# Resolve the TCSS stylesheet shipped alongside this file.
_STYLES_DIR = Path(__file__).resolve().parent / "styles"


class ForgeApp(App[None]):
    """Root Textual application for the Forge TUI.

    Lifecycle
    ---------
    1. WelcomeScreen is pushed if settings.json is missing.
    2. HomeScreen is pushed if config exists.
    3. When the user selects a conversation, HomeScreen pushes ChatScreen
       on top (via ``app.open_chat``).
    4. Settings and Help are modal screens that push/pop cleanly.
    """

    TITLE = "Forge"
    SUB_TITLE = "Autonomous Engineering Environment"
    CSS_PATH = str(_STYLES_DIR / "forge.tcss")

    BINDINGS = [
        Binding("f1", "show_help", "Help", show=True),
    ]

    def __init__(self, client: ForgeClient | None = None) -> None:
        super().__init__()
        self._client_provided = client is not None
        self.client = client or ForgeClient()

    async def on_mount(self) -> None:
        """Push the home screen on startup, or welcome if first run."""
        if self._client_provided:
            self._start_main_flow()
            return
        if self._needs_onboarding():
            self.push_screen(WelcomeScreen(), self._on_welcome_finished)
        else:
            self._start_main_flow()

    # Common provider env-var names that the config system reads (pattern: {PROVIDER}_API_KEY).
    _KNOWN_API_KEY_ENV_VARS: tuple[str, ...] = (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_AI_API_KEY",
        "XAI_API_KEY",
        "MISTRAL_API_KEY",
        "OPENROUTER_API_KEY",
        "GROQ_API_KEY",
        "FORGE_LLM_API_KEY",
    )

    @classmethod
    def _needs_onboarding(cls) -> bool:
        """Return True when the welcome wizard should be shown.

        Returns False if an API key is already available via:
        - settings.json (llm_api_key is set and non-empty)
        - Any well-known provider environment variable

        This prevents the wizard from firing when a developer already has
        their API keys in the shell environment, while still showing it for
        fresh users whose bootstrap script copied the minimal template.
        """
        import json
        import os

        # 1. Check environment variables first — fastest, no I/O
        for var in cls._KNOWN_API_KEY_ENV_VARS:
            if os.environ.get(var, "").strip():
                return False

        # 2. Fall back to settings.json
        settings_path = Path.cwd() / "settings.json"
        if not settings_path.exists():
            return True
        try:
            with open(settings_path, encoding="utf-8") as f:
                data = json.load(f)
            key = data.get("llm_api_key")
            return not key  # None, empty string, or missing → needs onboarding
        except Exception:
            return True

    def _on_welcome_finished(self, setup_completed: bool | None) -> None:
        """Called when user finishes the onboarding wizard."""
        if not setup_completed:
            self.exit()
            return
        self.notify("Systems initialized. Welcome to the Forge.", severity="information")
        self._start_main_flow()

    def _start_main_flow(self) -> None:
        """Load home screen and verify connectivity."""
        self.push_screen(HomeScreen(self.client))
        # Check if server is up
        self.run_worker(self._check_connectivity())

    async def _check_connectivity(self) -> None:
        """Silently check if the backend is reachable."""
        is_up = await self.client.health_check()
        if not is_up:
            self.notify(
                "Forge backend is offline. Start it with 'uv run forge serve'",
                severity="error",
                timeout=10,
            )

    # ── global actions ────────────────────────────────────────────

    def action_show_help(self) -> None:
        """Show the help screen."""
        self.push_screen(HelpScreen())

    async def action_quit(self) -> None:
        """Gracefully close the client then exit."""
        try:
            await self.client.close()
        except Exception:
            pass
        self.exit()

    # ── navigation helpers (called by child screens) ──────────────

    def open_chat(self, conversation_id: str) -> None:
        """Push the chat screen for a given conversation."""
        from tui.screens.chat import ChatScreen

        self.push_screen(ChatScreen(self.client, conversation_id))

    def open_settings(self) -> None:
        """Push the settings screen."""
        from tui.screens.settings import SettingsScreen

        self.push_screen(SettingsScreen(self.client))

    def open_summary(self) -> None:
        """Push the end-of-day summary screen."""
        from tui.screens.summary import SummaryScreen

        self.push_screen(SummaryScreen())
