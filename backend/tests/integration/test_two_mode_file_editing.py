from __future__ import annotations

from types import SimpleNamespace

from backend.engine.file_edit_protocol import (
    apply_edit_from_transaction,
    get_transaction_store,
    parse_editor_response,
)
from backend.execution.action_execution_server_helpers import edit_via_file_editor
from backend.execution.utils.file_editor import FileEditor
from backend.ledger.observation import FileEditObservation


def test_two_mode_content_reaches_existing_file_editor_pipeline(tmp_path):
    target = tmp_path / 'app.py'
    target.write_text('def value():\n    return 1\n', encoding='utf-8')

    store = get_transaction_store()
    txn = store.create_transaction(
        'integration_session',
        'app.py',
        'replace_range',
        {'start_line': 2, 'end_line': 2, 'security_risk': 'LOW'},
    )
    raw_content = '    return 42\n'
    response = (
        '<file_edit>\n'
        f'{raw_content}'
        f'{txn.delimiter}\n'
        '</file_edit>\n'
    )

    parsed = parse_editor_response(response, txn)
    assert parsed.ok
    action = apply_edit_from_transaction(parsed.content, txn)

    executor = SimpleNamespace(
        file_editor=FileEditor(workspace_root=tmp_path),
        _is_auto_lint_enabled=lambda: True,
    )
    obs = edit_via_file_editor(executor, action)

    assert isinstance(obs, FileEditObservation)
    assert '[EDIT_DIFF]' in obs.content
    assert obs.tool_result['ok'] is True
    assert target.read_text(encoding='utf-8') == 'def value():\n    return 42\n'
    store.clear_active_transaction('integration_session')
