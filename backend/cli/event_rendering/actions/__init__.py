"""Composed action renderer mixin."""

from __future__ import annotations

from backend.cli.event_rendering.actions.browser import _ActionBrowserMixin
from backend.cli.event_rendering.actions.dispatch import _ActionDispatchMixin
from backend.cli.event_rendering.actions.exploration import _ActionExplorationMixin
from backend.cli.event_rendering.actions.file import _ActionFileMixin
from backend.cli.event_rendering.actions.mcp import _ActionMcpMixin
from backend.cli.event_rendering.actions.message import _ActionMessageMixin
from backend.cli.event_rendering.actions.meta import _ActionMetaMixin
from backend.cli.event_rendering.actions.shell import _ActionShellMixin
from backend.cli.event_rendering.actions.terminal import _ActionTerminalMixin


class ActionRenderersMixin(
    _ActionDispatchMixin,
    _ActionMessageMixin,
    _ActionShellMixin,
    _ActionFileMixin,
    _ActionMcpMixin,
    _ActionBrowserMixin,
    _ActionExplorationMixin,
    _ActionTerminalMixin,
    _ActionMetaMixin,
):
    """Per-action ``_render_*_action`` renderers + dispatch."""


__all__ = ['ActionRenderersMixin']
