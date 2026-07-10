"""Validate settings.template.json against the runtime config schema."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.core.config import AppConfig
from backend.core.config.config_loader import load_from_json
from backend.core.constants import DEFAULT_AGENT_NAME

_REPO_ROOT = Path(__file__).resolve().parents[4]
_TEMPLATE_PATH = _REPO_ROOT / 'settings.template.json'


@pytest.mark.parametrize('template_path', [_TEMPLATE_PATH])
def test_settings_template_loads_without_schema_drift(template_path: Path) -> None:
    data = json.loads(template_path.read_text(encoding='utf-8'))

    agent_overrides = data.get('agent')
    assert isinstance(agent_overrides, dict)
    assert DEFAULT_AGENT_NAME in agent_overrides
    assert 'agent' not in agent_overrides

    security = data.get('security')
    assert isinstance(security, dict)
    assert security.get('execution_profile') == 'standard'
    assert security.get('windows_shell') == 'powershell'

    mcp_config = data.get('mcp_config')
    assert isinstance(mcp_config, dict)
    server_names = [s['name'] for s in mcp_config.get('servers', [])]
    assert 'shadcn' in server_names
    assert 'github' in server_names
    assert 'rigour' in server_names

    cfg = AppConfig()
    load_from_json(cfg, str(template_path))

    orchestrator = cfg.get_agent_config(DEFAULT_AGENT_NAME)
    assert orchestrator.autonomy_level == 'balanced'
    assert cfg.security.execution_profile == 'standard'
    assert cfg.security.windows_shell == 'powershell'


def test_settings_template_mcp_matches_defaults() -> None:
    from backend.core.config.mcp_defaults import default_user_mcp_config

    data = json.loads(_TEMPLATE_PATH.read_text(encoding='utf-8'))
    assert data['mcp_config'] == default_user_mcp_config()


def test_settings_template_exposes_lsp_and_dap_config() -> None:
    from backend.core.config.tool_integration_defaults import (
        default_dap_config,
        default_lsp_config,
    )

    data = json.loads(_TEMPLATE_PATH.read_text(encoding='utf-8'))
    assert data['lsp_config'] == default_lsp_config()
    assert data['dap_config'] == default_dap_config()


def test_settings_template_security_matches_init_defaults() -> None:
    from backend.cli.onboarding.settings_defaults import default_init_security_block

    data = json.loads(_TEMPLATE_PATH.read_text(encoding='utf-8'))
    assert data['security'] == default_init_security_block()
