from __future__ import annotations

import pytest

from backend.orchestration.file_edits.file_state_tracker import (
    FileStateMiddleware,
    FileStateTracker,
    _extract_removed_symbols,
    _find_symbol_references,
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
async def test_middleware_does_not_record_failed_edit_as_modified(tmp_path) -> None:
    from backend.ledger.observation import ErrorObservation

    f = tmp_path / 'target.py'
    f.write_text('x = 1\n', encoding='utf-8')

    mw = FileStateMiddleware()
    action = _file_edit_action(str(f), 'replace_string')
    ctx = _make_ctx(action)

    await mw.observe(ctx, ErrorObservation('replace_string old_string was not found'))

    assert mw.tracker.has_been_modified_recently(str(f)) is False
    assert mw.tracker.has_been_read_recently(str(f)) is False


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
