from __future__ import annotations

import os

import pytest

from backend.orchestration.file_state_tracker import (
    FileStateMiddleware,
    FileStateTracker,
    _extract_removed_symbols,
    _find_symbol_references,
    _normalize_path_key,
    file_manifest_path,
)
from backend.orchestration.tool_pipeline import ToolInvocationContext


def test_manifest_path_uses_agent_state_dir(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda project_root=None: tmp_path,
    )
    assert file_manifest_path() == tmp_path / 'file_manifest.json'


def test_record_keeps_highest_priority_action() -> None:
    tracker = FileStateTracker()

    tracker.record('src/app.py', 'read')
    tracker.record('src/app.py', 'modified')
    tracker.record('src/app.py', 'read')

    assert tracker.to_dict()['src/app.py']['action'] == 'modified'


def test_load_from_dict_restores_entries() -> None:
    tracker = FileStateTracker()
    tracker.load_from_dict({'src/app.py': {'action': 'created', 'timestamp': 123.0}})

    summary = tracker.get_summary()
    assert 'created: src/app.py' in summary


def test_read_snapshot_stale_guard_enabled_by_default(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """File state guard is enabled by default — stale check detects disk changes."""
    monkeypatch.delenv('GRINTA_FILE_STATE_GUARD', raising=False)
    monkeypatch.delenv('SECURITY_FILE_STATE_GUARD', raising=False)
    monkeypatch.chdir(tmp_path)
    f = tmp_path / 'stale.txt'
    f.write_text('version-one\n', encoding='utf-8')
    tracker = FileStateTracker()
    tracker.record_read_snapshot_from_disk('stale.txt')
    f.write_text('version-two\n', encoding='utf-8')
    msg = tracker.check_read_stale('stale.txt')
    assert msg is not None
    assert 'changed on disk' in (msg or '')


def test_read_snapshot_stale_guard_disabled_via_env(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """File state guard can be disabled via GRINTA_FILE_STATE_GUARD=0."""
    monkeypatch.setenv('GRINTA_FILE_STATE_GUARD', '0')
    monkeypatch.chdir(tmp_path)
    f = tmp_path / 'stale.txt'
    f.write_text('version-one\n', encoding='utf-8')
    tracker = FileStateTracker()
    tracker.record_read_snapshot_from_disk('stale.txt')
    f.write_text('version-two\n', encoding='utf-8')
    msg = tracker.check_read_stale('stale.txt')
    assert msg is None


def test_read_snapshot_not_stale_when_content_matches(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mtime can move without content change; hash match allows edit (Claude-style)."""
    monkeypatch.chdir(tmp_path)
    f = tmp_path / 'same.txt'
    body = b'stable-bytes'
    f.write_bytes(body)
    tracker = FileStateTracker()
    tracker.record_read_snapshot_from_disk('same.txt')
    snap = tracker._read_snapshots.get(_normalize_path_key('same.txt') or '')
    assert snap is not None
    os.utime(f, (snap.mtime + 10, snap.mtime + 10))
    assert tracker.check_read_stale('same.txt') is None


def test_invalidate_read_snapshot(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    f = tmp_path / 'x.txt'
    f.write_text('a', encoding='utf-8')
    tracker = FileStateTracker()
    tracker.record_read_snapshot_from_disk('x.txt')
    assert _normalize_path_key('x.txt') in tracker._read_snapshots
    tracker.invalidate_read_snapshot('x.txt')
    assert _normalize_path_key('x.txt') not in tracker._read_snapshots


# ---------------------------------------------------------------------------
# FileStateMiddleware enforcement tests
# ---------------------------------------------------------------------------


def _make_ctx(action, *, controller=None, state=None) -> ToolInvocationContext:
    """Build a minimal ToolInvocationContext for middleware tests."""
    from unittest.mock import MagicMock

    return ToolInvocationContext(
        controller=controller or MagicMock(),
        action=action,
        state=state or MagicMock(),
    )


def _file_edit_action(path: str, command: str):
    """Minimal stand-in for FileEditAction."""
    from unittest.mock import MagicMock

    a = MagicMock()
    a.__class__.__name__ = 'FileEditAction'
    a.path = path
    a.command = command
    return a


@pytest.mark.asyncio
async def test_middleware_blocks_str_replace_without_prior_read(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """File state guard is enabled by default — editing without prior read is blocked."""
    monkeypatch.delenv('GRINTA_FILE_STATE_GUARD', raising=False)
    monkeypatch.delenv('SECURITY_FILE_STATE_GUARD', raising=False)
    monkeypatch.chdir(tmp_path)
    f = tmp_path / 'target.py'
    f.write_text('x = 1\n', encoding='utf-8')

    mw = FileStateMiddleware()
    action = _file_edit_action(str(f), 'str_replace')
    ctx = _make_ctx(action)

    await mw.execute(ctx)

    assert ctx.blocked is True
    assert 'FILE_STATE_GUARD' in (ctx.block_reason or '')


@pytest.mark.asyncio
async def test_middleware_allows_str_replace_without_prior_read_when_guard_disabled(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When guard is disabled, editing without prior read is allowed."""
    monkeypatch.setenv('GRINTA_FILE_STATE_GUARD', '0')
    monkeypatch.chdir(tmp_path)
    f = tmp_path / 'target.py'
    f.write_text('x = 1\n', encoding='utf-8')

    mw = FileStateMiddleware()
    action = _file_edit_action(str(f), 'str_replace')
    ctx = _make_ctx(action)

    await mw.execute(ctx)

    assert ctx.blocked is False


@pytest.mark.asyncio
async def test_middleware_allows_str_replace_after_read(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Editing a file that was already read in this session must not be blocked."""
    monkeypatch.chdir(tmp_path)
    f = tmp_path / 'target.py'
    f.write_text('x = 1\n', encoding='utf-8')

    mw = FileStateMiddleware()
    mw.tracker.record(str(f), 'read')
    action = _file_edit_action(str(f), 'str_replace')
    ctx = _make_ctx(action)

    await mw.execute(ctx)

    assert ctx.blocked is False


@pytest.mark.asyncio
async def test_middleware_allows_edit_on_new_nonexistent_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Creating a new file that does not exist yet must not be blocked."""
    monkeypatch.chdir(tmp_path)
    new_path = str(tmp_path / 'brand_new.py')

    mw = FileStateMiddleware()
    action = _file_edit_action(new_path, 'str_replace')
    ctx = _make_ctx(action)

    await mw.execute(ctx)

    assert ctx.blocked is False


@pytest.mark.asyncio
async def test_middleware_allows_mutating_edit_on_stale_file_when_guard_disabled(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When guard is disabled, stale files are not blocked."""
    monkeypatch.setenv('GRINTA_FILE_STATE_GUARD', '0')
    monkeypatch.chdir(tmp_path)
    f = tmp_path / 'stale.py'
    f.write_text('v1\n', encoding='utf-8')

    mw = FileStateMiddleware()
    mw.tracker.record(str(f), 'read')
    mw.tracker.record_read_snapshot_from_disk(str(f))

    key = _normalize_path_key(str(f))
    assert key is not None
    snap = mw.tracker._read_snapshots[key]
    future_mtime = snap.mtime + 10
    os.utime(f, (future_mtime, future_mtime))
    f.write_text('v2\n', encoding='utf-8')
    os.utime(f, (future_mtime, future_mtime))

    action = _file_edit_action(str(f), 'write')
    ctx = _make_ctx(action)

    await mw.execute(ctx)

    assert ctx.blocked is False


@pytest.mark.asyncio
async def test_middleware_blocks_mutating_edit_on_stale_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """File state guard is enabled by default — editing a stale file is blocked."""
    monkeypatch.delenv('GRINTA_FILE_STATE_GUARD', raising=False)
    monkeypatch.delenv('SECURITY_FILE_STATE_GUARD', raising=False)
    monkeypatch.chdir(tmp_path)
    f = tmp_path / 'stale.py'
    f.write_text('v1\n', encoding='utf-8')

    mw = FileStateMiddleware()
    mw.tracker.record(str(f), 'read')
    mw.tracker.record_read_snapshot_from_disk(str(f))

    key = _normalize_path_key(str(f))
    assert key is not None
    snap = mw.tracker._read_snapshots[key]
    future_mtime = snap.mtime + 10
    os.utime(f, (future_mtime, future_mtime))
    f.write_text('v2\n', encoding='utf-8')
    os.utime(f, (future_mtime, future_mtime))

    action = _file_edit_action(str(f), 'write')
    ctx = _make_ctx(action)

    await mw.execute(ctx)

    assert ctx.blocked is True
    assert 'FILE_STATE_GUARD' in (ctx.block_reason or '')


# ---------------------------------------------------------------------------
# create_file gate tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_middleware_allows_create_file_on_existing_without_read(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """create_file is a full overwrite — no anchor text to mismatch — so it
    must NOT be blocked by the read-before-edit guard even on existing files.
    """
    monkeypatch.chdir(tmp_path)
    f = tmp_path / 'models.py'
    f.write_text('class Foo: pass\n', encoding='utf-8')

    mw = FileStateMiddleware()
    action = _file_edit_action(str(f), 'create_file')
    ctx = _make_ctx(action)

    await mw.execute(ctx)

    assert ctx.blocked is False


@pytest.mark.asyncio
async def test_middleware_allows_create_file_on_existing_after_read(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """create_file on an existing file must be allowed when read first."""
    monkeypatch.chdir(tmp_path)
    f = tmp_path / 'models.py'
    f.write_text('class Foo: pass\n', encoding='utf-8')

    mw = FileStateMiddleware()
    mw.tracker.record(str(f), 'read')
    action = _file_edit_action(str(f), 'create_file')
    ctx = _make_ctx(action)

    await mw.execute(ctx)

    assert ctx.blocked is False


@pytest.mark.asyncio
async def test_middleware_allows_create_file_on_new_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """create_file on a path that does not yet exist must never be blocked."""
    monkeypatch.chdir(tmp_path)
    new_path = str(tmp_path / 'new_module.py')  # file does not exist

    mw = FileStateMiddleware()
    action = _file_edit_action(new_path, 'create_file')
    ctx = _make_ctx(action)

    await mw.execute(ctx)

    assert ctx.blocked is False


# ---------------------------------------------------------------------------
# Blast-radius helper tests
# ---------------------------------------------------------------------------


def test_extract_removed_symbols_finds_class_and_def() -> None:
    diff = (
        '--- a/models.py\n'
        '+++ b/models.py\n'
        '@@ -1,5 +1,3 @@\n'
        '-class ExpenseParticipant:\n'
        '-    pass\n'
        '+class ExpenseSplit:\n'
        '+    pass\n'
        '-def calculate_balance():\n'
        '+def compute_balance():\n'
    )
    symbols = _extract_removed_symbols(diff)
    assert 'ExpenseParticipant' in symbols
    assert 'calculate_balance' in symbols
    # Added names must NOT appear (they start with '+')
    assert 'ExpenseSplit' not in symbols
    assert 'compute_balance' not in symbols


def test_extract_removed_symbols_empty_on_additions_only() -> None:
    diff = '+class NewThing:\n+    pass\n+def new_fn():\n+    pass\n'
    assert _extract_removed_symbols(diff) == []


def test_find_symbol_references_returns_matching_lines(tmp_path) -> None:
    logic = tmp_path / 'logic.py'
    logic.write_text(
        'from models import ExpenseParticipant\n'
        'def run():\n'
        '    return ExpenseParticipant()\n',
        encoding='utf-8',
    )
    models = tmp_path / 'models.py'
    models.write_text('class ExpenseSplit:\n    pass\n', encoding='utf-8')

    refs = _find_symbol_references(
        ['ExpenseParticipant'],
        [str(logic), str(models)],
        exclude_path=str(models),
    )
    assert str(logic) in refs
    assert 'ExpenseParticipant' in refs


def test_find_symbol_references_excludes_mutated_file(tmp_path) -> None:
    """The file being written must not appear in its own blast-radius report."""
    f = tmp_path / 'models.py'
    f.write_text('class ExpenseParticipant:\n    pass\n', encoding='utf-8')

    refs = _find_symbol_references(
        ['ExpenseParticipant'],
        [str(f)],
        exclude_path=str(f),
    )
    assert refs == ''
