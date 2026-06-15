"""Shared imports and helpers for CLI frontend."""

from __future__ import annotations
import asyncio
import io
import json
import os
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from rich.console import Console
from rich.text import Text
from backend.cli.event_rendering.panels import task_panel_signature
from backend.cli.event_rendering.sidebar import build_task_list_panel
from backend.cli.settings.confirmation import _risk_label
from backend.cli.display.diff_renderer import DiffPanel
from backend.cli.event_renderer import CLIEventRenderer
from backend.cli.display.hud import HUDBar
from backend.cli.main import (
    _configure_redirected_streams,
    _read_piped_stdin,
    show_grinta_splash,
)
from backend.cli.display.reasoning_display import ReasoningDisplay
from backend.cli.repl import Repl
from backend.cli.repl.slash_command_registry import (
    _build_command_completer,
    _build_help_markdown,
    _parse_slash_command,
    _prompt_toolkit_available,
    _supports_prompt_session,
)
from backend.cli.tui.app import _render_thinking_with_diff
from backend.core.config import AppConfig
from backend.core.constants import LLM_API_KEY_SETTINGS_PLACEHOLDER
from backend.core.enums import ActionSecurityRisk, AgentState, EventSource
from backend.inference.metrics import Metrics, ResponseLatency, TokenUsage
from backend.ledger.action import (
    CmdRunAction,
    FileEditAction,
    FileReadAction,
    MessageAction,
    StreamingChunkAction,
)
from backend.ledger.observation import (
    AgentThinkObservation,
    CmdOutputObservation,
    ErrorObservation,
    TaskTrackingObservation,
)
from backend.orchestration.state.state import PlanStep
from backend.persistence.locations import get_project_local_data_root
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
