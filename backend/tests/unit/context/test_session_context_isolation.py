"""Session-scoped context stores must not leak across new sessions."""

from __future__ import annotations

import json

from backend.context.compactor.pre_condensation_snapshot import (
    _snapshot_path,
    load_snapshot,
)
from backend.context.memory.session_context import scoped_agent_path
from backend.context.memory.session_memory import (
    _session_memory_path,
    load_session_memory,
    session_memory_exists,
)
from backend.engine.tools.scratchpad import _notes_path
from backend.engine.tools.working_memory import (
    _memory_path,
    get_current_session_id,
    set_current_session_id,
)


def test_session_memory_path_is_scoped_by_session_id(tmp_path, monkeypatch):
    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda: tmp_path,
    )
    set_current_session_id('session-a')
    assert _session_memory_path() == tmp_path / 'session_memory_session-a.md'

    set_current_session_id('session-b')
    assert _session_memory_path() == tmp_path / 'session_memory_session-b.md'
    assert _session_memory_path() != tmp_path / 'session_memory_session-a.md'


def test_snapshot_path_is_scoped_by_session_id(tmp_path, monkeypatch):
    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda: tmp_path,
    )
    set_current_session_id('abc-123')
    assert _snapshot_path() == tmp_path / 'pre_condensation_snapshot_abc-123.json'


def test_new_session_does_not_read_prior_session_memory(tmp_path, monkeypatch):
    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda: tmp_path,
    )
    legacy = tmp_path / 'session_memory.md'
    legacy.write_text('# Session Memory\n\nOld Raft project context', encoding='utf-8')

    set_current_session_id('brand-new-session')
    assert not _session_memory_path().exists()
    assert get_current_session_id() == 'brand-new-session'
    assert _session_memory_path().name == 'session_memory_brand-new-session.md'
    assert load_session_memory() == ''
    assert not session_memory_exists()


def test_legacy_workspace_files_are_never_used_when_session_bound(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda: tmp_path,
    )
    set_current_session_id('sess-new')
    (tmp_path / 'session_memory.md').write_text('legacy memory', encoding='utf-8')
    (tmp_path / 'working_memory.json').write_text(
        '{"findings":"legacy"}', encoding='utf-8'
    )
    (tmp_path / 'pre_condensation_snapshot.json').write_text(
        json.dumps({'decisions': ['legacy']}), encoding='utf-8'
    )
    (tmp_path / 'agent_notes.json').write_text('{"task":"legacy"}', encoding='utf-8')

    assert _session_memory_path().name == 'session_memory_sess-new.md'
    assert _memory_path().name == 'working_memory_sess-new.json'
    assert _snapshot_path().name == 'pre_condensation_snapshot_sess-new.json'
    assert _notes_path().name == 'agent_notes_sess-new.json'
    assert load_session_memory() == ''
    assert load_snapshot() is None


def test_unbound_session_uses_quarantined_paths_not_legacy(tmp_path, monkeypatch):
    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda: tmp_path,
    )
    set_current_session_id(None)
    (tmp_path / 'session_memory.md').write_text('legacy', encoding='utf-8')

    path = scoped_agent_path('session_memory', '.md')
    assert path.parent.name == '.session_context_unbound'
    assert load_session_memory() == ''


def test_session_event_logger_fallback_resolves_session_id(tmp_path, monkeypatch):
    """When the contextvar is not set, resolve_session_id should fall back
    to the bound session event logger's session id.
    """
    from backend.context.memory.session_context import resolve_session_id
    from backend.core.logging.session_event_logger import (
        close_session_event_logger,
        get_bound_session_id,
    )

    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda: tmp_path,
    )
    set_current_session_id(None)

    # Without a bound logger, resolution returns None
    assert get_bound_session_id() is None
    assert resolve_session_id() is None

    # Simulate the session event logger being bound (as happens at session start)
    import backend.core.logging.session_event_logger as sel_mod

    monkeypatch.setattr(sel_mod, '_SESSION_ID', 'logger-bound-sid')

    assert get_bound_session_id() == 'logger-bound-sid'
    assert resolve_session_id() == 'logger-bound-sid'

    # The contextvar takes priority over the logger fallback
    set_current_session_id('ctxvar-sid')
    assert resolve_session_id() == 'ctxvar-sid'

    # Cleanup
    set_current_session_id(None)
    close_session_event_logger()
