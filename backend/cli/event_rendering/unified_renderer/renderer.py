"""Composed activity card factory."""

from __future__ import annotations

from backend.cli.event_rendering.unified_renderer.mixins.shell import _ShellMixin
from backend.cli.event_rendering.unified_renderer.mixins.file import _FileMixin
from backend.cli.event_rendering.unified_renderer.mixins.mcp import _McpMixin
from backend.cli.event_rendering.unified_renderer.mixins.browser import _BrowserMixin
from backend.cli.event_rendering.unified_renderer.mixins.code import _CodeMixin
from backend.cli.event_rendering.unified_renderer.mixins.delegate import _DelegateMixin
from backend.cli.event_rendering.unified_renderer.mixins.terminal import _TerminalMixin
from backend.cli.event_rendering.unified_renderer.mixins.status import _StatusMixin
from backend.cli.event_rendering.unified_renderer.mixins.exploration import _ExplorationMixin


class ActivityRenderer(
    _ShellMixin,
    _FileMixin,
    _McpMixin,
    _BrowserMixin,
    _CodeMixin,
    _DelegateMixin,
    _TerminalMixin,
    _StatusMixin,
    _ExplorationMixin,
):
    """Factory for creating activity cards from agent events."""
