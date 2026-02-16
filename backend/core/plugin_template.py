"""Forge plugin template — copy and adapt for your own plugin.

Quick start:

1. Copy this file to your plugin package.
2. Rename ``MyPlugin`` and update ``name``, ``version``, ``description``.
3. Override only the ``on_*`` hooks you need.
4. Wire the ``register()`` function as an entry point in your ``pyproject.toml``:

   [project.entry-points."forge.plugins"]
   my_plugin = "my_plugin:register"

5. ``pip install -e .`` your package — Forge discovers it automatically.

Available hooks (all async, all optional):

  on_action_pre(action)               → Action          (chain)
  on_action_post(action, observation)  → Observation     (chain)
  on_event(event)                      → None            (fan-out)
  on_session_start(session_id, meta)   → None            (fan-out)
  on_session_end(session_id, meta)     → None            (fan-out)
  on_llm_pre(messages, **kwargs)       → messages        (chain)
  on_llm_post(response)               → response        (chain)
  on_condense(original, condensed, m)  → condensed       (chain)
  on_memory_recall(recall_type, content) → content       (chain)
  on_tool_invoke(tool_name, tool_args)  → tool_args      (chain)
"""

from __future__ import annotations

import logging
from typing import Any

from backend.core.plugin import ForgePlugin, PluginRegistry

logger = logging.getLogger(__name__)


class MyPlugin(ForgePlugin):
    """Example Forge plugin — replace with your implementation."""

    name = "my-plugin"
    version = "0.1.0"
    description = "A template plugin for Forge."
    min_api_version = (1, 0)

    # ── Override the hooks you need ─────────────────────

    async def on_action_pre(self, action):
        # Example: log every action before execution
        logger.info("[%s] action_pre: %s", self.name, type(action).__name__)
        return action

    async def on_event(self, event):
        # Example: log events for external telemetry
        pass

    async def on_session_start(self, session_id: str, metadata: dict[str, Any]):
        logger.info("[%s] session started: %s", self.name, session_id)

    async def on_session_end(self, session_id: str, metadata: dict[str, Any]):
        logger.info("[%s] session ended: %s", self.name, session_id)

    # ── Validation ──────────────────────────────────────

    def validate(self) -> list[str]:
        return super().validate()
        # Add your own checks here, e.g.:
        # if not os.environ.get("MY_PLUGIN_API_KEY"):
        #     warnings.append("MY_PLUGIN_API_KEY env var not set")


def register(registry: PluginRegistry) -> None:
    """Entry point called by Forge's plugin discovery."""
    plugin = MyPlugin()
    validation_warnings = plugin.validate()
    if validation_warnings:
        for w in validation_warnings:
            logger.warning("[%s] validation: %s", plugin.name, w)
    registry.register(plugin)
