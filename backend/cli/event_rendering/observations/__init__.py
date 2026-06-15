"""Composed observation renderer mixin."""

from __future__ import annotations

from backend.cli.event_rendering.observations.dispatch import _ObsDispatchMixin
from backend.cli.event_rendering.observations.think_browser import _ObsThinkBrowserMixin
from backend.cli.event_rendering.observations.shell import _ObsShellMixin
from backend.cli.event_rendering.observations.file import _ObsFileMixin
from backend.cli.event_rendering.observations.error import _ObsErrorMixin
from backend.cli.event_rendering.observations.status import _ObsStatusMixin
from backend.cli.event_rendering.observations.mcp import _ObsMcpMixin
from backend.cli.event_rendering.observations.terminal import _ObsTerminalMixin
from backend.cli.event_rendering.observations.exploration import _ObsExplorationMixin
from backend.cli.event_rendering.observations.misc import _ObsMiscMixin


class ObservationRenderersMixin(
    _ObsDispatchMixin,
    _ObsThinkBrowserMixin,
    _ObsShellMixin,
    _ObsFileMixin,
    _ObsErrorMixin,
    _ObsStatusMixin,
    _ObsMcpMixin,
    _ObsTerminalMixin,
    _ObsExplorationMixin,
    _ObsMiscMixin,
):
    """Per-observation ``_render_*_observation`` renderers + dispatch."""


__all__ = ['ObservationRenderersMixin']
