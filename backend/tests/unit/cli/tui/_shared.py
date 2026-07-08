"""Shared imports and helpers for Headless TUI."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from rich.console import Console as RichConsole
from rich.markdown import Markdown
from textual.containers import Container
from textual.widgets import Label, Select, Static, TextArea

from backend.cli.display.hud import HUDBar
from backend.cli.display.reasoning_display import ReasoningDisplay
from backend.cli.event_rendering.unified_renderer import ActivityRenderer
from backend.cli.theme import grinta_rich_theme_styles
from backend.cli.tui.app import (
    HUD,
    CommunicatePromptWidget,
    GrintaScreen,
    InputBar,
    RendererDrainRequested,
    TUIRenderer,
    WelcomeWidget,
    _strip_terminal_control_literals,
)
from backend.cli.tui.dialogs import GrintaHelpDialog, GrintaSessionsDialog
from backend.cli.tui.main import GrintaTUIApp
from backend.cli.tui.widgets.activity_card import (
    AgentMessage,
    LiveResponse,
    OrientLine,
    ThinkingIndicator,
)
from backend.cli.tui.widgets.small import ScrollTailBadge
from backend.cli.tui.widgets.unified_diff_view import UnifiedDiffRow, UnifiedDiffView
from backend.core.enums import AgentState, EventSource
from backend.ledger.action import (
    AgentThinkAction,
    CondensationRequestAction,
    DelegateTaskAction,
    FileEditAction,
    FileReadAction,
    MessageAction,
    StreamingChunkAction,
    SystemHintAction,
)
from backend.ledger.action.browser_tool import BrowserToolAction
from backend.ledger.action.code_nav import LspQueryAction
from backend.ledger.action.commands import CmdRunAction
from backend.ledger.action.mcp import MCPAction
from backend.ledger.action.terminal import (
    TerminalInputAction,
    TerminalReadAction,
    TerminalRunAction,
    TerminalWaitAction,
)
from backend.ledger.observation import (
    AgentCondensationObservation,
    AgentThinkObservation,
    StatusObservation,
)
from backend.ledger.observation.agent import (
    AgentStateChangedObservation,
    DelegateTaskObservation,
)
from backend.ledger.observation.browser_screenshot import BrowserScreenshotObservation
from backend.ledger.observation.code_nav import LspQueryObservation
from backend.ledger.observation.commands import CmdOutputObservation
from backend.ledger.observation.error import ErrorObservation
from backend.ledger.observation.files import (
    FileEditObservation,
    FileReadObservation,
)
from backend.ledger.observation.mcp import MCPObservation
from backend.ledger.observation.task_tracking import TaskTrackingObservation
from backend.ledger.observation.terminal import TerminalObservation


def _get_screen(app: GrintaTUIApp) -> GrintaScreen:
    """Helper: query via app.screen since app.query_one uses default screen."""
    return app.screen  # type: ignore[return-value]


def _static_render_plain(static: Static) -> str:
    rendered = static.renderable
    if hasattr(rendered, 'plain'):
        return str(rendered.plain)
    console = RichConsole()
    with console.capture() as capture:
        console.print(rendered)
    return capture.get()


async def _await_at_bottom(display, pilot, *, attempts: int = 40) -> None:
    """Wait for programmatic follow-tail / force_scroll_end to settle."""
    for _ in range(attempts):
        if getattr(display, '_suppress_scroll_sync', False):
            await pilot.pause()
            continue
        display._sync_scroll_state_from_position()
        if display._was_at_bottom():
            return
        await pilot.pause()
    if getattr(display, '_suppress_scroll_sync', False):
        display._release_programmatic_scroll()
        await pilot.pause()
    display._sync_scroll_state_from_position()
    if not display._was_at_bottom():
        display.force_scroll_end()
        await pilot.pause()
        display._sync_scroll_state_from_position()
    assert display._was_at_bottom()


async def _fill_scrollable_transcript(display, pilot, *, count: int = 80) -> None:
    for idx in range(count):
        display.append_widget(Static(f'transcript line {idx}'))
    await pilot.pause()
    display.force_scroll_end()
    await _await_at_bottom(display, pilot)
    assert display.max_scroll_y > 0


__all__ = [
    'ActivityRenderer',
    'AgentCondensationObservation',
    'AgentMessage',
    'AgentState',
    'AgentStateChangedObservation',
    'AgentThinkAction',
    'AgentThinkObservation',
    'AsyncMock',
    'BrowserScreenshotObservation',
    'BrowserToolAction',
    'CmdOutputObservation',
    'CmdRunAction',
    'CommunicatePromptWidget',
    'CondensationRequestAction',
    'Container',
    'DelegateTaskAction',
    'DelegateTaskObservation',
    'ErrorObservation',
    'EventSource',
    'FileEditAction',
    'FileEditObservation',
    'FileReadAction',
    'FileReadObservation',
    'GrintaHelpDialog',
    'GrintaScreen',
    'GrintaSessionsDialog',
    'GrintaTUIApp',
    'HUD',
    'HUDBar',
    'InputBar',
    'Label',
    'LiveResponse',
    'LspQueryAction',
    'LspQueryObservation',
    'MCPAction',
    'MCPObservation',
    'MagicMock',
    'Markdown',
    'MessageAction',
    'OrientLine',
    'PropertyMock',
    'ReasoningDisplay',
    'RendererDrainRequested',
    'RichConsole',
    'ScrollTailBadge',
    'Select',
    'SimpleNamespace',
    'Static',
    'StatusObservation',
    'StreamingChunkAction',
    'TUIRenderer',
    'TaskTrackingObservation',
    'TerminalInputAction',
    'TerminalObservation',
    'TerminalReadAction',
    'TerminalRunAction',
    'TextArea',
    'ThinkingIndicator',
    'UnifiedDiffRow',
    'UnifiedDiffView',
    'WelcomeWidget',
    '_await_at_bottom',
    '_fill_scrollable_transcript',
    '_get_screen',
    '_static_render_plain',
    '_strip_terminal_control_literals',
    'asyncio',
    'grinta_rich_theme_styles',
    'pytest',
]
