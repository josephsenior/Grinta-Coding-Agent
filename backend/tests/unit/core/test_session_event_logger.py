"""Tests for unified session.jsonl event logger."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.core.logging.session_event_logger import (
    bind_session_event_logger,
    close_session_event_logger,
    emit_session_event,
    is_noise_message,
)


@pytest.fixture(autouse=True)
def _reset_session_logger() -> None:
    close_session_event_logger()
    # Also clear the runtime context (controller/llm_config) AND the last
    # captured hash so tests don't leak into each other.
    from backend.core.logging.session_context import clear_runtime_context

    clear_runtime_context()
    yield
    close_session_event_logger()
    from backend.core.logging.session_context import clear_runtime_context

    clear_runtime_context()


def test_is_noise_message_filters_streaming_chunks() -> None:
    assert is_noise_message('on_event received StreamingChunkAction (id=1)')
    assert is_noise_message('[streaming-dbg] chunk')
    assert not is_noise_message('Setting agent state from RUNNING to FINISHED')


def test_emit_writes_jsonl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        'backend.core.logging.session_event_logger.LOG_TO_FILE', True
    )
    bind_session_event_logger('sess-1', str(tmp_path), workspace_segment='ws-seg')
    emit_session_event('USER_TURN', {'text': 'hello'})
    lines = [
        line
        for line in (tmp_path / 'session.jsonl')
        .read_text(encoding='utf-8')
        .splitlines()
        if line.strip()
    ]
    assert len(lines) >= 1
    record = json.loads(lines[-1])
    assert record['event'] == 'USER_TURN'
    assert record['payload']['text'] == 'hello'
    assert record['session_id'] == 'sess-1'
    assert record['workspace'] == 'ws-seg'


def test_wire_events_respect_grinta_log_wire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        'backend.core.logging.session_event_logger.LOG_TO_FILE', True
    )
    bind_session_event_logger('sess-1', str(tmp_path))
    with patch(
        'backend.core.logging.session_event_logger.wire_log_enabled',
        return_value=False,
    ):
        emit_session_event('WIRE_PROMPT', {'messages': []})
    emit_session_event('PROMPT_SHAPE', {'roles': {'user': 1}})
    events = [
        json.loads(line)['event']
        for line in (tmp_path / 'session.jsonl').read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]
    assert 'WIRE_PROMPT' not in events
    assert 'PROMPT_SHAPE' in events


def test_bind_emits_session_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        'backend.core.logging.session_event_logger.LOG_TO_FILE', True
    )
    bind_session_event_logger('abc', str(tmp_path), workspace_segment='ws')
    events = [
        json.loads(line)['event']
        for line in (tmp_path / 'session.jsonl').read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]
    assert events[0] == 'SESSION_START'


def test_bind_suppresses_empty_session_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When bind runs before ``register_runtime_context``, the captured
    snapshot is fully ``None``. Suppress the empty SESSION_CONTEXT line so
    the first one in the log is the authoritative one emitted after
    controller/llm_config are registered.
    """
    monkeypatch.setattr(
        'backend.core.logging.session_event_logger.LOG_TO_FILE', True
    )
    # No register_runtime_context() call — snapshot is all None.
    bind_session_event_logger('sess-2', str(tmp_path))
    events = [
        json.loads(line)['event']
        for line in (tmp_path / 'session.jsonl').read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]
    assert events == ['SESSION_START']
    assert 'SESSION_CONTEXT' not in events


def test_bind_emits_session_context_when_runtime_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the runtime context is registered before bind, the SESSION_CONTEXT
    line is emitted with the resolved values."""
    monkeypatch.setattr(
        'backend.core.logging.session_event_logger.LOG_TO_FILE', True
    )
    from backend.core.logging.session_context import register_runtime_context

    agent_config = SimpleNamespace(mode='full', autonomy_level='high')
    agent = SimpleNamespace(config=agent_config)
    state = SimpleNamespace(extra_data={'active_run_mode': 'plan'})
    autonomy_ctrl = SimpleNamespace(autonomy_level='high')
    controller = SimpleNamespace(agent=agent, state=state, autonomy_controller=autonomy_ctrl)
    llm_config = SimpleNamespace(
        model='test/model',
        custom_llm_provider='openai',
        reasoning_effort='medium',
        temperature=0.0,
        top_p=1.0,
        top_k=None,
        native_tool_calling=True,
        context_window_tokens=128000,
        max_output_tokens=8192,
        prompt_history_token_budget=None,
        prompt_history_budget_ratio=None,
        prompt_history_max_events=None,
    )

    register_runtime_context(controller=controller, llm_config=llm_config)
    bind_session_event_logger('sess-3', str(tmp_path))
    events = [
        json.loads(line)['event']
        for line in (tmp_path / 'session.jsonl').read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]
    assert events[0] == 'SESSION_START'
    assert 'SESSION_CONTEXT' in events


def test_wire_log_enabled_default_true() -> None:
    import backend.core.constants as constants_mod

    assert constants_mod.GRINTA_LOG_WIRE is True


def test_emit_merges_caller_ctx_with_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Caller-supplied ctx must MERGE into the live snapshot, not replace it.

    Regression: TOOL_RESULT events passed ``ctx={'astep_id': ...}`` and the
    envelope replaced the snapshot, dropping the ``model``/``provider``/
    ``autonomy``/etc. fields. Every TOOL_RESULT line ended up with
    ``ctx.model=null`` and the audit rollup had to back-fill from
    ``last_known_model``.
    """
    monkeypatch.setattr(
        'backend.core.logging.session_event_logger.LOG_TO_FILE', True
    )
    from backend.core.logging.session_context import register_runtime_context

    agent_config = SimpleNamespace(mode='full', autonomy_level='high')
    agent = SimpleNamespace(config=agent_config)
    state = SimpleNamespace(extra_data={'active_run_mode': 'plan'})
    autonomy_ctrl = SimpleNamespace(autonomy_level='high')
    controller = SimpleNamespace(agent=agent, state=state, autonomy_controller=autonomy_ctrl)
    llm_config = SimpleNamespace(
        model='test/model',
        custom_llm_provider='openai',
        reasoning_effort='medium',
        temperature=0.0, top_p=1.0, top_k=None, native_tool_calling=True,
        context_window_tokens=128000, max_output_tokens=8192,
        prompt_history_token_budget=None, prompt_history_budget_ratio=None,
        prompt_history_max_events=None,
    )
    register_runtime_context(controller=controller, llm_config=llm_config)
    bind_session_event_logger('sess-merge', str(tmp_path))
    # Emit a TOOL_RESULT with a partial ctx arg.
    emit_session_event(
        'TOOL_RESULT',
        {'tool': 'replace_string', 'ok': True},
        ctx={'astep_id': 'ast-42'},
    )
    lines = [
        json.loads(line)
        for line in (tmp_path / 'session.jsonl').read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]
    tool_result = [r for r in lines if r['event'] == 'TOOL_RESULT'][0]
    assert tool_result['ctx']['model'] == 'test/model'
    assert tool_result['ctx']['provider'] == 'openai'
    assert tool_result['ctx']['mode'] == 'full'
    assert tool_result['ctx']['autonomy'] == 'high'
    assert tool_result['ctx']['astep_id'] == 'ast-42'


def test_emit_caller_ctx_can_override_snapshot_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Caller ctx can override snapshot fields when needed (e.g. to inject
    a debug override of model)."""
    monkeypatch.setattr(
        'backend.core.logging.session_event_logger.LOG_TO_FILE', True
    )
    from backend.core.logging.session_context import register_runtime_context

    agent_config = SimpleNamespace(mode='full', autonomy_level='high')
    agent = SimpleNamespace(config=agent_config)
    state = SimpleNamespace(extra_data={'active_run_mode': 'plan'})
    autonomy_ctrl = SimpleNamespace(autonomy_level='high')
    controller = SimpleNamespace(agent=agent, state=state, autonomy_controller=autonomy_ctrl)
    llm_config = SimpleNamespace(
        model='real/model', custom_llm_provider='openai',
        reasoning_effort='medium',
        temperature=0.0, top_p=1.0, top_k=None, native_tool_calling=True,
        context_window_tokens=128000, max_output_tokens=8192,
        prompt_history_token_budget=None, prompt_history_budget_ratio=None,
        prompt_history_max_events=None,
    )
    register_runtime_context(controller=controller, llm_config=llm_config)
    bind_session_event_logger('sess-override', str(tmp_path))
    emit_session_event(
        'TOOL_RESULT',
        {'tool': 'x', 'ok': True},
        ctx={'model': 'debug/override'},
    )
    lines = [
        json.loads(line)
        for line in (tmp_path / 'session.jsonl').read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]
    tool_result = [r for r in lines if r['event'] == 'TOOL_RESULT'][0]
    assert tool_result['ctx']['model'] == 'debug/override'
    # Other snapshot fields still preserved.
    assert tool_result['ctx']['provider'] == 'openai'
