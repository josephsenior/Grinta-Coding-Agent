"""Unified activity renderer for Grinta.

Provides a single rendering pipeline that produces consistent output for both
CLI (Rich) and TUI (Textual) modes. Uses activity cards with badges, verbs,
and structured content instead of heavy bordered panels.
"""

from backend.cli.event_rendering.unified_renderer.renderer import ActivityRenderer
from backend.cli.event_rendering.unified_renderer.types import (
    ActivityCard,
    ActivityLine,
)

__all__ = [
    'ActivityCard',
    'ActivityLine',
    'ActivityRenderer',
]
