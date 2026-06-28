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


def semantic_recall_active(
    config: Any,
    *,
    vector_store: Any | None = None,
    require_live_store: bool = False,
) -> bool:
    """Return True when semantic ``memory(recall)`` should be exposed.

    When *require_live_store* is True (runtime tool/prompt assembly), the
    vector store must have initialized successfully — config + ``[rag]`` alone
    is not enough.
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
