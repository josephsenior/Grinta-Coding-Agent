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
    1. WelcomeScreen is pushed if config.toml is missing.
    2. HomeScreen is pushed if config exists.
    3. When the user selects a conversation, HomeScreen pushes ChatScreen
       on top (via ``app.open_chat``).
    4. Settings and Help are modal screens that push/pop cleanly.
    """

    TITLE = "Forge"
    SUB_TITLE = "AI-Powered Development"
    CSS_PATH = str(_STYLES_DIR / "forge.tcss")

    BINDINGS = [
        Binding("f1", "show_help", "Help", show=True),
    ]

    def __init__(self, client: ForgeClient | None = None) -> None:
        super().__init__()
        self.client = client or ForgeClient()

    async def on_mount(self) -> None:
        """Push the home screen on startup, or welcome if first run."""
        config_path = Path.cwd() / "config.toml"
        if not config_path.exists():
            self.push_screen(WelcomeScreen(), self._on_welcome_finished)
        else:
            self._start_main_flow()

    def _on_welcome_finished(self, setup_completed: bool) -> None:
        """Called when user finishes the onboarding wizard."""
        if setup_completed:
            self.notify("Setup complete! Welcome to Forge.", severity="information")
            self._start_main_flow()
        else:
            self.exit()

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
