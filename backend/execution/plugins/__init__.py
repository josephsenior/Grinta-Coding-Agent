"""Runtime plugin registration and convenience exports.

.. note:: **Two plugin systems exist in App:**

   * :mod:`backend.core.plugin` — *core hooks* (host-side, lifecycle hooks,
     entry-point group ``app.plugins``).
    * **This module** — *runtime plugins* (run inside the runtime process,
     entry-point group ``app.runtime_plugins``).

   They are intentionally separate.  See :mod:`backend.core.plugin` module
   docstring for a comparison table.

Plugin Discovery
----------------
Plugins are registered via two mechanisms:

1. **Built-in registry** — ``ALL_PLUGINS`` dict below (hardcoded).
2. **Entry-point discovery** — third-party packages can declare a
   ``app.runtime_plugins`` entry point group to be auto-discovered::

       [project.entry-points."app.runtime_plugins"]
       my_plugin = "my_package.plugin:MyPlugin"

   The entry point value must be a callable that returns a ``Plugin``
   instance.

Enable / disable plugins via the ``APP_PLUGINS`` env variable
(comma-separated allowlist) or programmatically via
``filter_plugins_by_config()``.
"""

from __future__ import annotations

import importlib.metadata
import os
from collections.abc import Callable

from backend.core.logger import app_logger as logger
from backend.execution.plugins.agent_skills import (
    AgentSkillsPlugin,
    AgentSkillsRequirement,
)
from backend.execution.plugins.requirement import Plugin, PluginRequirement

__all__ = [
    "AgentSkillsPlugin",
    "AgentSkillsRequirement",
    "Plugin",
    "PluginRequirement",
    "ALL_PLUGINS",
    "__runtime_plugin_contract_frozen__",
    "discover_plugins",
    "filter_plugins_by_config",
]

# Contract stability — the ``Plugin`` / ``PluginRequirement`` ABCs
# are frozen and follow semver.  Third-party runtime plugins may
# rely on this guarantee.
__runtime_plugin_contract_frozen__: bool = True

# ------------------------------------------------------------------
# Built-in plugin registry
# ------------------------------------------------------------------
ALL_PLUGINS: dict[str, Callable[[], Plugin]] = {
    "agent_skills": AgentSkillsPlugin,
}


# ------------------------------------------------------------------
# Entry-point auto-discovery
# ------------------------------------------------------------------
_EP_GROUP = "app.runtime_plugins"


def discover_plugins() -> dict[str, Callable[[], Plugin]]:
    """Merge built-in and entry-point-discovered plugins.

    Third-party packages register via
    ``[project.entry-points."app.runtime_plugins"]``.
    Conflicts are logged and the built-in version wins.
    """
    merged: dict[str, Callable[[], Plugin]] = dict(ALL_PLUGINS)
    try:
        eps = importlib.metadata.entry_points(group=_EP_GROUP)
        for ep in eps:
            if ep.name in merged:
                logger.debug(
                    "Plugin %r already registered (built-in); ignoring entry-point from %s",
                    ep.name,
                    ep.value,
                )
                continue
            try:
                merged[ep.name] = ep.load()
                logger.info(
                    "Discovered plugin %r via entry-point: %s", ep.name, ep.value
                )
            except Exception:
                logger.warning(
                    "Failed to load plugin entry-point %r (%s)",
                    ep.name,
                    ep.value,
                    exc_info=True,
                )
    except Exception:
        logger.debug("Entry-point discovery unavailable", exc_info=True)
    return merged


# ------------------------------------------------------------------
# Config-based filtering
# ------------------------------------------------------------------


def filter_plugins_by_config(
    plugins: list[PluginRequirement],
) -> list[PluginRequirement]:
    """Filter plugins against the ``APP_PLUGINS`` env allowlist.

    If the env var is unset or empty, all plugins pass through (opt-out model).
    Otherwise, only plugins whose ``name`` appears in the comma-separated
    allowlist are kept.
    """
    raw = os.getenv("APP_PLUGINS", "").strip()
    if not raw:
        return plugins  # no filter — all enabled

    allowed = {n.strip().lower() for n in raw.split(",") if n.strip()}
    filtered = [p for p in plugins if p.name.lower() in allowed]
    disabled = [p.name for p in plugins if p.name.lower() not in allowed]
    if disabled:
        logger.info(
            "Plugins disabled by APP_PLUGINS allowlist: %s",
            ", ".join(disabled),
        )
    return filtered
