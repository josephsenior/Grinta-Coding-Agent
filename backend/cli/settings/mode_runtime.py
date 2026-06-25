"""Apply interaction-mode changes to a live agent runtime."""

from __future__ import annotations

import logging
from typing import Any

from backend.core.interaction_modes import is_chat_mode, normalize_interaction_mode

logger = logging.getLogger(__name__)


def sync_active_run_mode_extra_data(controller: object, mode: str) -> None:
    """Mirror interaction mode into ``state.extra_data['active_run_mode']``."""
    state = getattr(controller, 'state', None)
    extra_data = getattr(state, 'extra_data', None) if state is not None else None
    if not isinstance(extra_data, dict):
        return
    normalized = normalize_interaction_mode(mode)
    if is_chat_mode(normalized):
        extra_data.pop('active_run_mode', None)
    else:
        extra_data['active_run_mode'] = normalized


def rebuild_agent_toolset(agent: object, *, mode: str | None = None) -> None:
    """Refresh ``agent.tools`` after interaction mode changes."""
    if agent is None:
        return
    running_config = getattr(agent, 'config', None)
    if mode is not None and running_config is not None:
        running_config.mode = normalize_interaction_mode(mode)
    planner = getattr(agent, 'planner', None)
    if planner is None:
        return
    if mode is not None:
        planner_config = getattr(planner, '_config', None)
        if planner_config is not None:
            planner_config.mode = normalize_interaction_mode(mode)
    if hasattr(planner, 'build_toolset'):
        try:
            agent.tools = planner.build_toolset()
        except Exception:
            logger.warning('Failed to rebuild toolset after mode change', exc_info=True)


def apply_interaction_mode_to_controller(controller: object, mode: str) -> None:
    """Propagate mode to agent config, toolset, and run-scoped extra_data."""
    agent = getattr(controller, 'agent', None)
    if agent is not None:
        rebuild_agent_toolset(agent, mode=mode)
    sync_active_run_mode_extra_data(controller, mode)


__all__ = [
    'apply_interaction_mode_to_controller',
    'rebuild_agent_toolset',
    'sync_active_run_mode_extra_data',
]
