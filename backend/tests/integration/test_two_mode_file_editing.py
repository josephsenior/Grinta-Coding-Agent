from __future__ import annotations

from types import SimpleNamespace

from backend.engine.file_edit_protocol import (
    apply_edit_from_transaction,
    get_transaction_store,
    parse_editor_response,
)
from backend.ledger.action import FileEditAction
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
    assert isinstance(action, FileEditAction)

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


def test_two_mode_edit_symbols_payload_reaches_existing_structure_pipeline(tmp_path):
    target = tmp_path / 'app.py'
    target.write_text(
        'def a():\n    return 1\n\n\ndef b():\n    return 2\n',
        encoding='utf-8',
    )

    store = get_transaction_store()
    txn = store.create_transaction(
        'integration_edit_symbols',
        str(target),
        'edit_symbols',
        {
            'security_risk': 'LOW',
            'editor_items': [
                {'name': 'a', 'delimiter': 'GRINTA_ITEM_END_a'},
                {'name': 'b', 'delimiter': 'GRINTA_ITEM_END_b'},
            ],
        },
    )
    raw_payload = (
        '<symbol name="a">\n'
        '    return 10\n'
        'GRINTA_ITEM_END_a\n'
        '</symbol>\n'
        '<symbol name="b">\n'
        '    return 20\n'
        'GRINTA_ITEM_END_b\n'
        '</symbol>\n'
    )
    response = '<file_edit>\n' + raw_payload + f'{txn.delimiter}\n</file_edit>\n'

    parsed = parse_editor_response(response, txn)
    assert parsed.ok
    action = apply_edit_from_transaction(parsed.content, txn)
    assert isinstance(action, FileEditAction)

    executor = SimpleNamespace(
        file_editor=FileEditor(workspace_root=tmp_path),
        _is_auto_lint_enabled=lambda: True,
    )
    obs = edit_via_file_editor(executor, action)

    assert isinstance(obs, FileEditObservation)
    assert obs.tool_result['ok'] is True
    assert 'return 10' in target.read_text(encoding='utf-8')
    assert 'return 20' in target.read_text(encoding='utf-8')
    store.clear_active_transaction('integration_edit_symbols')


def test_two_mode_multi_edit_payload_reaches_existing_batch_pipeline(
    tmp_path, monkeypatch
):
    first = tmp_path / 'a.py'
    second = tmp_path / 'b.py'
    first.write_text('x = 1\n', encoding='utf-8')
    second.write_text('y = 1\n', encoding='utf-8')
    monkeypatch.chdir(tmp_path)

    store = get_transaction_store()
    txn = store.create_transaction(
        'integration_multi_edit',
        '<batch>',
        'multi_edit',
        {
            'security_risk': 'LOW',
            'editor_items': [
                {
                    'index': 1,
                    'delimiter': 'GRINTA_ITEM_END_1',
                    'path': 'a.py',
                    'operation': 'replace_range',
                    'start_line': 1,
                    'end_line': 1,
                },
                {
                    'index': 2,
                    'delimiter': 'GRINTA_ITEM_END_2',
                    'path': 'b.py',
                    'operation': 'replace_range',
                    'start_line': 1,
                    'end_line': 1,
                },
            ],
        },
    )
    raw_payload = (
        '<edit index="1">\n'
        'x = 2\n'
        'GRINTA_ITEM_END_1\n'
        '</edit>\n'
        '<edit index="2">\n'
        'y = 2\n'
        'GRINTA_ITEM_END_2\n'
        '</edit>\n'
    )
    response = '<file_edit>\n' + raw_payload + f'{txn.delimiter}\n</file_edit>\n'

    parsed = parse_editor_response(response, txn)
    assert parsed.ok
    action = apply_edit_from_transaction(parsed.content, txn)
    assert isinstance(action, FileEditAction)

    executor = SimpleNamespace(
        file_editor=FileEditor(workspace_root=tmp_path),
        _is_auto_lint_enabled=lambda: True,
    )
    obs = edit_via_file_editor(executor, action)

    assert isinstance(obs, FileEditObservation)
    assert obs.tool_result['ok'] is True
    assert first.read_text(encoding='utf-8') == 'x = 2\n'
    assert second.read_text(encoding='utf-8') == 'y = 2\n'
    store.clear_active_transaction('integration_multi_edit')
