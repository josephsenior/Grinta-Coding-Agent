"""Runtime detection for pip optional extras ([rag], [browser])."""

from __future__ import annotations

import importlib.util
from typing import Any

from backend.core.constants import DEFAULT_AGENT_NAME


def _optional_extra_installed(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def is_rag_extra_available() -> bool:
    """Return True when the ``[rag]`` extra (chromadb stack) is installed."""
    return _optional_extra_installed('chromadb')


def is_browser_extra_available() -> bool:
    """Return True when the ``[browser]`` extra (browser-use) is installed."""
    return _optional_extra_installed('browser_use')


def _resolve_agent_config(config: Any) -> Any:
    if hasattr(config, 'get_agent_config'):
        name = getattr(config, 'default_agent', None) or DEFAULT_AGENT_NAME
        return config.get_agent_config(name)
    return config


def browser_tool_enabled(config: Any) -> bool:
    """Config allows browser **and** the ``[browser]`` extra is installed."""
    agent = _resolve_agent_config(config)
    return (
        bool(getattr(agent, 'enable_browsing', True)) and is_browser_extra_available()
    )


def vector_memory_enabled(config: Any) -> bool:
    """Config allows vector memory **and** the ``[rag]`` extra is installed."""
    agent = _resolve_agent_config(config)
    return (
        bool(getattr(agent, 'enable_vector_memory', False)) and is_rag_extra_available()
    )
