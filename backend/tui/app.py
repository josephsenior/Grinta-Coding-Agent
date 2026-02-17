"""Forge TUI — main Textual application."""

from __future__ import annotations

import logging
from pathlib import Path

from textual.app import App
from textual.binding import Binding

from backend.tui.client import ForgeClient
from backend.tui.screens.help import HelpScreen
from backend.tui.screens.home import HomeScreen

logger = logging.getLogger("forge.tui")

# Resolve the TCSS stylesheet shipped alongside this file.
_STYLES_DIR = Path(__file__).resolve().parent / "styles"


class ForgeApp(App[None]):
    """Root Textual application for the Forge TUI.

    Lifecycle
    ---------
    1. HomeScreen is pushed on startup.
    2. When the user selects a conversation, HomeScreen pushes ChatScreen
       on top (via ``app.open_chat``).
    3. When ChatScreen is dismissed (Ctrl+Q), we naturally pop back to
       HomeScreen — no callbacks or asyncio hacks required.
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
        """Push the home screen on startup."""
        self.push_screen(HomeScreen(self.client))

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
        from backend.tui.screens.chat import ChatScreen

        self.push_screen(ChatScreen(self.client, conversation_id))

    def open_settings(self) -> None:
        """Push the settings screen."""
        from backend.tui.screens.settings import SettingsScreen

        self.push_screen(SettingsScreen(self.client))

    def open_summary(self) -> None:
        """Push the end-of-day summary screen."""
        from backend.tui.screens.summary import SummaryScreen

        self.push_screen(SummaryScreen())
