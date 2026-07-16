"""Default top-level LSP / DAP blocks for settings.json."""

from __future__ import annotations

from typing import Any

# Agent-block keys must not appear in settings.json; use top-level lsp_config/dap_config.
DEPRECATED_AGENT_SETTINGS_KEYS = frozenset(
    {
        'enable_lsp_query',
        'enable_debugger',
        'enable_meta_cognition',
    }
)


def default_lsp_config() -> dict[str, Any]:
    """Return the default ``lsp_config`` block for settings.json."""
    return {'enabled': False}


def default_dap_config() -> dict[str, Any]:
    """Return the default ``dap_config`` block for settings.json."""
    return {'enabled': False}


__all__ = [
    'DEPRECATED_AGENT_SETTINGS_KEYS',
    'default_dap_config',
    'default_lsp_config',
]
