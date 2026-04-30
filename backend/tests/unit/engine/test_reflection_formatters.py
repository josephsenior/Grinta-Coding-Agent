"""Tests for backend.engine.reflection formatting helpers."""

from __future__ import annotations

from types import SimpleNamespace

from backend.core.contracts.state import State
from backend.engine.reflection import (
    build_reflection_data_parts,
    format_reflection_initial_request,
    format_reflection_metrics,
    format_reflection_modified_files,
    format_reflection_progress,
)


def test_format_reflection_progress_empty_when_no_iteration() -> None:
    state = State(session_id='s')
    assert format_reflection_progress(state) == ''


def test_format_reflection_progress_with_turn_and_budget() -> None:
    state = State(session_id='s')
    state.iteration_flag.current_value = 3
    state.iteration_flag.max_value = 10
    out = format_reflection_progress(state)
    assert 'Turn 3' in out and '30%' in out


def test_format_reflection_metrics_token_usage_and_cost() -> None:
    state = State(session_id='s')
    state.metrics = SimpleNamespace(
        accumulated_token_usage=SimpleNamespace(prompt_tokens=50, context_window=100),
        accumulated_cost=1.23,
    )
    lines = format_reflection_metrics(state)
    assert any('50%' in ln or '50/100' in ln for ln in lines)
    assert any('1.2300' in ln for ln in lines)


def test_format_reflection_modified_files_truncates_after_five() -> None:
    files = [f'f{i}.py' for i in range(10)]
    out = format_reflection_modified_files(files)
    assert '+5 more' in out
    assert 'f5.py' in out


def test_format_reflection_initial_request_swallows_errors() -> None:
    mm = SimpleNamespace(
        get_initial_user_message=lambda _h: (_ for _ in ()).throw(RuntimeError('x'))
    )
    assert format_reflection_initial_request(mm, []) == ''


def test_build_reflection_data_parts_fallback_when_empty() -> None:
    state = State(session_id='s')
    state.history = []
    mm = SimpleNamespace(get_initial_user_message=lambda _h: None)
    parts = build_reflection_data_parts(state, mm, [])
    assert any('No data available' in p for p in parts)
