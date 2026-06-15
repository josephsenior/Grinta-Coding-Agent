"""Shared imports and helpers for Headless TUI."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock

import pytest
from rich.console import Console as RichConsole
from textual.widgets import Static, TextArea

from backend.cli.display.hud import HUDBar
from backend.cli.display.reasoning_display import ReasoningDisplay
from backend.cli.tui.app import (
    GrintaScreen,
    TUIRenderer,
)
from backend.cli.tui.main import GrintaTUIApp
from backend.cli.tui.helpers import _strip_terminal_control_literals
from backend.cli.tui.widgets.small import RendererDrainRequested
from backend.cli.tui.widgets.welcome import WelcomeWidget


def _get_screen(app: GrintaTUIApp) -> GrintaScreen:
    """Helper: query via app.screen since app.query_one uses default screen."""
    return app.screen  # type: ignore[return-value]


async def _fill_scrollable_transcript(display, pilot, *, count: int = 80) -> None:
    for idx in range(count):
        display.append_widget(Static(f'transcript line {idx}'))
    await pilot.pause()
    display.force_scroll_end()
    await pilot.pause()
    assert display.max_scroll_y > 0
