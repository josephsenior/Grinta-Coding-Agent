"""Shared defaults for ``grinta init`` and env-detected settings persistence."""

from __future__ import annotations

from typing import Any

from backend.core.constants import LLM_API_KEY_SETTINGS_PLACEHOLDER


def default_init_security_block() -> dict[str, Any]:
    """Return the canonical ``security`` block aligned with ``settings.template.json``."""
    return {
        'windows_shell': 'bash',
        'execution_profile': 'standard',
        'enforce_security': True,
        'block_high_risk': False,
        'allow_network_commands': False,
        'allow_package_installs': False,
        'allow_background_processes': False,
        'allow_sensitive_path_access': False,
        'allow_read_outside_workspace': False,
        'allow_mcp_arg_repair': False,
        'additional_read_roots': [],
    }


def default_init_agent_block() -> dict[str, Any]:
    """Return the default ``agent`` block for new installs."""
    return {
        'Orchestrator': {
            'mode': 'agent',
            'autonomy_level': 'balanced',
        },
    }


def settings_api_key_value(provider: str, api_key: str, *, requires_key: bool) -> str:
    """Return the settings.json api-key value for the selected provider."""
    if api_key or requires_key:
        return LLM_API_KEY_SETTINGS_PLACEHOLDER
    return ''


def build_init_settings(
    *,
    provider: str,
    model: str,
    api_key: str,
    base_url: str = '',
    requires_api_key: bool = True,
) -> dict[str, Any]:
    """Build a full init-shaped ``settings.json`` payload."""
    from backend.core.config.mcp_defaults import default_user_mcp_config
    from backend.core.config.tool_integration_defaults import (
        default_dap_config,
        default_lsp_config,
    )

    return {
        'llm_provider': provider,
        'llm_model': model,
        'llm_api_key': settings_api_key_value(
            provider,
            api_key,
            requires_key=requires_api_key,
        ),
        'llm_base_url': base_url,
        'agent': default_init_agent_block(),
        'security': default_init_security_block(),
        'lsp_config': default_lsp_config(),
        'dap_config': default_dap_config(),
        'mcp_config': default_user_mcp_config(),
    }


__all__ = [
    'build_init_settings',
    'default_init_agent_block',
    'default_init_security_block',
    'settings_api_key_value',
]
