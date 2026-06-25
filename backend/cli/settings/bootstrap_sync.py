"""Sync persisted mode/autonomy from settings.json onto a live controller."""

from __future__ import annotations

from typing import Any


def sync_controller_persisted_settings(
    controller: Any,
    agent_name: str,
    *,
    config: Any | None = None,
    hud: Any | None = None,
) -> tuple[str, str]:
    """Apply persisted interaction mode and autonomy; optionally update HUD."""
    from backend.cli.settings import (
        sync_persisted_autonomy_to_controller,
        sync_persisted_interaction_mode_to_controller,
    )

    autonomy_level = sync_persisted_autonomy_to_controller(
        controller,
        agent_name,
        config=config,
    )
    interaction_mode = sync_persisted_interaction_mode_to_controller(
        controller,
        agent_name,
        config=config,
    )
    if hud is not None:
        if hasattr(hud, 'update_autonomy'):
            hud.update_autonomy(autonomy_level)
        if hasattr(hud, 'update_interaction_mode'):
            hud.update_interaction_mode(interaction_mode)
    return autonomy_level, interaction_mode


__all__ = ['sync_controller_persisted_settings']
