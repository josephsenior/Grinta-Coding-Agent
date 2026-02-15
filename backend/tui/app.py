"""Forge TUI — main Textual application."""

from __future__ import annotations

import logging
from pathlib import Path

from textual.app import App
from textual.binding import Binding

from backend.tui.client import ForgeClient
from backend.tui.screens.chat import ChatScreen
from backend.tui.screens.help import HelpScreen
from backend.tui.screens.home import HomeScreen

logger = logging.getLogger("forge.tui")

# Resolve the TCSS stylesheet shipped alongside this file.
_STYLES_DIR = Path(__file__).resolve().parent / "styles"


class ForgeApp(App[None]):
    """Root Textual application for the Forge TUI.

    Lifecycle:
      1. Show :class:`HomeScreen` so the user can pick / create a conversation.
      2. When the user selects a conversation, push :class:`ChatScreen`.
      3. When the chat screen is dismissed, return to HomeScreen.
    """

    TITLE = "Forge"
    SUB_TITLE = "AI-Powered Development"
    CSS_PATH = str(_STYLES_DIR / "forge.tcss")

    BINDINGS = [
        Binding("?", "show_help", "Help", show=False),
        Binding("h", "show_help", "Help", show=False),
    ]

    def __init__(self, client: ForgeClient) -> None:
        super().__init__()
        self.client = client

    async def on_mount(self) -> None:
        """Push the home screen on startup."""
        await self._show_home()

    async def _show_home(self) -> None:
        """Display the home screen and wait for a conversation selection."""

        def _on_home_dismiss(conversation_id: str | None) -> None:
            if conversation_id:
                self.push_screen(
                    ChatScreen(self.client, conversation_id),
                    callback=self._on_chat_dismiss,
                )

        self.push_screen(HomeScreen(self.client), callback=_on_home_dismiss)

    def _on_chat_dismiss(self, _result: None) -> None:
        """Called when the chat screen is dismissed — return to home."""
        import asyncio

        asyncio.ensure_future(self._show_home())

    async def action_quit(self) -> None:
        """Gracefully close the client then exit."""
        await self.client.close()
        self.exit()

    def action_show_help(self) -> None:
        """Show the help screen."""
        self.push_screen(HelpScreen())
