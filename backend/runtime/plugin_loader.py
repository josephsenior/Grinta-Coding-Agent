"""Plugin loading and initialization for the action execution server."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.core.logger import forge_logger as logger

if TYPE_CHECKING:
    from backend.runtime.plugins import Plugin


async def init_plugins(
    plugins_to_load: list[Plugin], username: str
) -> dict[str, Any]:
    """Initialize a list of plugins.

    Args:
        plugins_to_load: List of plugin instances to initialize.
        username: Username for plugin initialization.

    Returns:
        Dict mapping plugin name to plugin instance.
    """
    plugins: dict[str, Any] = {}
    for plugin in plugins_to_load:
        plugins[plugin.name] = plugin
        await plugin.initialize(username)
        logger.info("Plugin %s initialized", plugin.name)
    return plugins
