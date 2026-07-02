"""Planner integration tests for repo map injection."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from backend.engine.planner import OrchestratorPlanner


def _make_planner(**config_overrides):
    config = SimpleNamespace(
        enable_coding_preflight=False,
        enable_repo_map=True,
        map_tokens=800,
        symbol_index_mode='lazy',
        merge_control_system_into_primary=False,
        mode='agent',
        llm_config=SimpleNamespace(model='gpt-4o-mini'),
        **config_overrides,
    )
    llm = SimpleNamespace(config=SimpleNamespace(model='gpt-4o-mini'))
    return OrchestratorPlanner(llm=llm, config=config, safety_manager=SimpleNamespace())


def test_inject_repo_map_inserts_control_message() -> None:
    planner = _make_planner()
    messages = [
        {'role': 'system', 'content': 'sys'},
        {'role': 'user', 'content': 'please fix the backend api endpoint'},
    ]
    with patch(
        'backend.context.symbol_index.repo_map.build_repo_map_block',
        return_value='<REPO_MAP>map</REPO_MAP>',
    ):
        out = planner._inject_repo_map(messages, 'agent')
    assert any(
        msg.get('role') == 'system' and '<REPO_MAP>' in str(msg.get('content', ''))
        for msg in out
    )
