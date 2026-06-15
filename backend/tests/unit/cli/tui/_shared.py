"""Shared imports and helpers for Headless TUI."""

from __future__ import annotations

from textual.widgets import Static

from backend.cli.tui.app import (
    GrintaScreen,
)
from backend.cli.tui.main import GrintaTUIApp


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
