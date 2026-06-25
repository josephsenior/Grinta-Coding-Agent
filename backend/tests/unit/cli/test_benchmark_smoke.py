"""Minimal benchmark smoke tests for CI heavy/benchmark tier."""

from __future__ import annotations

import time

import pytest


@pytest.mark.benchmark
def test_settings_template_loads_under_budget() -> None:
    """settings.template.json should load quickly (cold parse smoke)."""
    import json
    from pathlib import Path

    start = time.perf_counter()
    path = Path(__file__).resolve().parents[4] / 'settings.template.json'
    payload = json.loads(path.read_text(encoding='utf-8'))
    elapsed = time.perf_counter() - start
    assert 'agent' in payload
    assert elapsed < 0.5, f'template load took {elapsed:.3f}s'


@pytest.mark.benchmark
def test_interaction_mode_gate_is_fast() -> None:
    """Mode gate checks should stay sub-millisecond per call."""
    from backend.core.interaction_modes import action_blocked_for_interaction_mode
    from backend.ledger.action.commands import CmdRunAction

    action = CmdRunAction(command='echo ok')
    start = time.perf_counter()
    for _ in range(1000):
        action_blocked_for_interaction_mode(action, 'chat')
    elapsed = time.perf_counter() - start
    assert elapsed < 0.25, f'1000 gate checks took {elapsed:.3f}s'


@pytest.mark.benchmark
def test_slash_hints_registry_build_is_fast() -> None:
    from backend.cli.repl.slash_registry_commands import slash_hints_from_registry

    start = time.perf_counter()
    hints = slash_hints_from_registry()
    elapsed = time.perf_counter() - start
    assert '/mode' in hints
    assert elapsed < 0.05
