"""Shared imports and helpers for CLI frontend."""

from __future__ import annotations

import asyncio
import io
from typing import cast
from unittest.mock import MagicMock

from rich.console import Console

from backend.cli.display.hud import HUDBar
from backend.cli.display.reasoning_display import ReasoningDisplay
from backend.cli.event_renderer import CLIEventRenderer
from backend.core.config import AppConfig


def _make_console(*, width: int = 120) -> Console:
    return Console(file=io.StringIO(), force_terminal=False, width=width)


def _make_config() -> AppConfig:
    return cast(AppConfig, MagicMock())


def _console_output(console: Console) -> str:
    file_obj = console.file
    assert isinstance(file_obj, io.StringIO)
    return file_obj.getvalue()


def _transcript_needle_count(console: Console, needle: str) -> int:
    """Count occurrences of *needle* in rendered console output (committed lines)."""
    return _console_output(console).count(needle)


def _make_renderer_sync() -> tuple[Console, HUDBar, CLIEventRenderer]:
    """Create a renderer without needing an event loop (for sync tests)."""
    console = _make_console()
    hud = HUDBar()
    loop = asyncio.new_event_loop()
    reasoning = ReasoningDisplay()
    renderer = CLIEventRenderer(console, hud, reasoning, loop=loop)
    return console, hud, renderer
