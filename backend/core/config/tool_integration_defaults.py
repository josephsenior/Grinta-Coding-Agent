"""Default top-level LSP / DAP blocks for settings.json."""

from __future__ import annotations

from typing import Any

# Agent-block keys replaced by ``lsp_config`` / ``dap_config`` in settings.json.
LEGACY_AGENT_TOOL_KEYS = frozenset({'enable_lsp_query', 'enable_debugger'})


def default_lsp_config() -> dict[str, Any]:
    """Return the default ``lsp_config`` block for settings.json."""
    return {'enabled': False}


def default_dap_config() -> dict[str, Any]:
    """Return the default ``dap_config`` block for settings.json."""
    return {'enabled': False}


def strip_legacy_agent_tool_keys(settings: dict[str, Any]) -> None:
    """Remove deprecated LSP/DAP agent keys from a settings payload in place."""
    agent_section = settings.get('agent')
    if not isinstance(agent_section, dict):
        return
    for agent_entry in agent_section.values():
        if not isinstance(agent_entry, dict):
            continue
        for key in LEGACY_AGENT_TOOL_KEYS:
            agent_entry.pop(key, None)


__all__ = [
    'LEGACY_AGENT_TOOL_KEYS',
    'default_dap_config',
    'default_lsp_config',
    'strip_legacy_agent_tool_keys',
]
