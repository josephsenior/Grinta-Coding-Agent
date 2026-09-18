"""Runtime feature gates: config flags plus what the machine actually provides."""

from __future__ import annotations

import functools
import importlib.util
from typing import Any

from backend.core.constants import DEFAULT_AGENT_NAME


def _optional_extra_installed(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


@functools.lru_cache(maxsize=1)
def _browser_binary_present() -> bool:
    """Whether a Chromium-family browser is installed (cached: filesystem probe)."""
    from backend.execution.browser._cdp_engine import find_browser_binary

    return find_browser_binary() is not None


def is_browser_available() -> bool:
    """Return True when a Chromium-based browser can be driven over CDP.

    The browser tool needs no Python package beyond Grinta's own dependencies;
    it drives Chrome, Edge, Chromium or Brave already installed on the machine.
    """
    return _browser_binary_present()


def _resolve_agent_config(config: Any) -> Any:
    if hasattr(config, 'get_agent_config'):
        name = getattr(config, 'default_agent', None) or DEFAULT_AGENT_NAME
        return config.get_agent_config(name)
    return config


def browser_tool_enabled(config: Any) -> bool:
    """Config allows browsing **and** a Chromium-family browser is installed."""
    agent = _resolve_agent_config(config)
    return bool(getattr(agent, 'enable_browsing', True)) and is_browser_available()


def vector_memory_enabled(config: Any) -> bool:
    """Config allows history search (``enable_vector_memory``, default on).

    History search runs on SQLite FTS5 from the standard library, so there is
    no install-time dependency to check — the config flag alone decides.
    """
    agent = _resolve_agent_config(config)
    return bool(getattr(agent, 'enable_vector_memory', False))


def semantic_recall_active(
    config: Any,
    *,
    vector_store: Any | None = None,
    require_live_store: bool = False,
) -> bool:
    """Return True when history search (``search_history``) should be exposed.

    When *require_live_store* is True (runtime tool/prompt assembly), the
    search store must have initialized successfully — the config flag alone
    is not enough, since the SQLite database can still fail to open.
    """
    if not vector_memory_enabled(config):
        return False
    if require_live_store:
        return vector_store is not None
    return True


def resolve_semantic_recall_for_prompt(
    config: Any,
    *,
    semantic_recall_active: bool | None = None,
) -> bool:
    """Prompt-time gate: prefer runtime flag from Orchestrator when set."""
    if semantic_recall_active is not None:
        return bool(semantic_recall_active)
    return vector_memory_enabled(config)
