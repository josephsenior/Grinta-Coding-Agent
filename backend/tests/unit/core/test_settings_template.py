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

    cfg = AppConfig()
    load_from_json(cfg, str(template_path))

    orchestrator = cfg.get_agent_config(DEFAULT_AGENT_NAME)
    assert orchestrator.autonomy_level == 'balanced'
    assert cfg.security.execution_profile == 'standard'
