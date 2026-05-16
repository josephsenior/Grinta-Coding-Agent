"""Grinta TUI — main runner that boots the Textual app.

This is the TUI equivalent of the CLI's Repl.run(). It creates the event loop,
bootstraps the agent, and runs the Textual application.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Respect the user's DEBUG setting; do not override it.
from rich.console import Console as RichConsole
from rich.theme import Theme as RichTheme
from textual.app import App

from backend.cli.hud import HUDBar
from backend.cli.reasoning_display import ReasoningDisplay

# ── Rich theme for consistent markup in RichLog/Static widgets ─────────────
_RICH_THEME = RichTheme({
    'repr.number': '#e9e9e9',
    'repr.string': '#54efae',
    'repr.bool': '#91abec',
    'repr.none': '#969aad',
    'repr.url': '#91abec',
    'repr.uuid': '#969aad',
})

if TYPE_CHECKING:
    from backend.cli.config_manager import AppConfig


class GrintaTUIApp(App):
    """Top-level Textual application shell."""

    TITLE = 'GRINTA'
    SUB_TITLE = 'AI-Powered Development Platform'

    def __init__(
        self,
        config: AppConfig,
        console: RichConsole,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        super().__init__()
        self._config = config
        self._console = console
        self._loop = loop
        self._hud = HUDBar()
        self._reasoning = ReasoningDisplay()
        self._session_running = True
        self._pending_confirm: asyncio.Event | None = None
        self._confirm_result: str | None = None
        self._event_stream: Any | None = None
        self._controller: Any | None = None
        self._agent_task: asyncio.Task[Any] | None = None
        self._renderer: Any | None = None
        self._input_lock = asyncio.Lock()
        self._screen: Any | None = None

        # Register Rich theme for consistent markup rendering
        self._console.push_theme(_RICH_THEME)

    def compose(self):
        """Layout is handled by the pushed screen."""
        return iter([])

    async def on_mount(self) -> None:
        from backend.cli.tui.app import GrintaScreen
        self._screen = await self.push_screen(GrintaScreen(
            config=self._config,
            console=self._console,
            loop=self._loop,
            hud=self._hud,
            reasoning=self._reasoning,
            app=self,
        ))

    def on_unmount(self) -> None:
        self._console.pop_theme()
        if self._event_stream is not None:
            try:
                self._event_stream.close()
            except Exception:
                pass
            self._event_stream = None
            self._screen = None

    def update_hud(self) -> None:
        screen = self.screen
        if hasattr(screen, 'update_hud'):
            screen.update_hud()


async def run_tui(
    config: AppConfig,
    console: RichConsole,
    *,
    verbose: bool = False,
) -> None:
    """Run the Grinta TUI. This is the TUI equivalent of Repl.run()."""
    loop = asyncio.get_running_loop()

    app = GrintaTUIApp(config=config, console=console, loop=loop)
    app._hud.update_model(config.get_llm_config().model or '(not set)')
    app._hud.update_workspace(
        str(Path(os.getcwd()).resolve())
        if not getattr(config, 'project_root', None)
        else str(getattr(config, 'project_root'))
    )
    app._hud.update_ledger('Starting')
    app._hud.update_agent_state('Starting')

    try:
        await app.run_async()
    except KeyboardInterrupt:
        pass
    finally:
        if app._agent_task and not app._agent_task.done():
            app._agent_task.cancel()
            try:
                await asyncio.wait_for(app._agent_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

        # Drain remaining tracked background tasks so asyncio.run() cleanup
        # doesn't hit RecursionError from Python 3.12's recursive Task.cancel().
        from backend.utils.async_utils import drain_background_tasks

        await drain_background_tasks(max_rounds=2, timeout=2.0)


async def _async_main_tui(
    config: AppConfig,
    console: RichConsole,
    *,
    model: str | None = None,
    show_splash: bool = False,
    minimal: bool = False,
    accessible: bool = False,
    verbose: bool = False,
) -> None:
    if model:
        from backend.cli.config_manager import update_model
        update_model(model)

    await run_tui(config, console, verbose=verbose)
