from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.core.errors import FunctionCallValidationError
from backend.engine.file_edit_protocol import (
    PROHIBITED_CONTENT_FIELDS,
    get_transaction_store,
    start_file_edit_transaction,
)
from backend.engine.function_calling import _handle_start_file_edit_tool
from backend.engine.tools.symbol_editor_tool import create_symbol_editor_tool
from backend.engine.tools.start_file_edit import create_start_file_edit_tool
from backend.ledger.action import StartFileEditAction
from backend.ledger.observation import ErrorObservation


def _walk_schema_keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _walk_schema_keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_schema_keys(value)


def test_start_file_edit_schema_does_not_accept_content_fields():
    schema = create_start_file_edit_tool()['function']['parameters']
    keys = set(_walk_schema_keys(schema))
    assert not (keys & PROHIBITED_CONTENT_FIELDS)


def test_start_file_edit_creates_start_action_for_content_operation():
    action = _handle_start_file_edit_tool(
        {
            'operation': 'replace_range',
            'path': 'app.py',
            'start_line': 1,
            'end_line': 2,
            'security_risk': 'LOW',
        }
    )
    assert isinstance(action, StartFileEditAction)
    assert action.operation == 'replace_range'
    assert action.metadata['start_line'] == 1


def test_start_file_edit_rejects_content_arguments():
    with pytest.raises(FunctionCallValidationError, match='does not accept'):
        _handle_start_file_edit_tool(
            {
                'operation': 'create',
                'path': 'app.py',
                'content': 'print(1)',
                'security_risk': 'LOW',
            }
        )


def test_start_file_edit_path_safety_still_runs(tmp_path):
    action = StartFileEditAction(
        path='../outside.py',
        operation='replace_range',
        metadata={'security_risk': 'LOW'},
        session_id='path_safety',
    )
    runtime = SimpleNamespace(workspace_root=tmp_path)
    obs = start_file_edit_transaction(runtime, action)
    assert isinstance(obs, ErrorObservation)
    assert get_transaction_store().get_active_transaction('path_safety') is None


def test_start_file_edit_unsupported_operation_fails_cleanly():
    with pytest.raises(FunctionCallValidationError, match='not supported'):
        _handle_start_file_edit_tool(
            {
                'operation': 'create',
                'path': 'app.py',
                'security_risk': 'LOW',
            }
        )


def test_start_file_edit_rejects_find_and_undo_operations():
    for operation in ('find_symbol', 'undo'):
        with pytest.raises(FunctionCallValidationError, match='not supported'):
            _handle_start_file_edit_tool(
                {
                    'operation': operation,
                    'path': 'app.py',
                    'security_risk': 'LOW',
                }
            )


def test_public_editor_schemas_do_not_expose_retired_edit_modes():
    start_ops = create_start_file_edit_tool()['function']['parameters']['properties']['operation']['enum']
    symbol_commands = create_symbol_editor_tool()['function']['parameters']['properties']['command']['enum']

    assert set(start_ops) == {'insert', 'replace_range', 'edit_symbol', 'edit_symbols', 'multi_edit'}
    assert {'edit_symbol', 'edit_symbols', 'rename_symbol', 'find_symbol', 'replace_range'} <= set(symbol_commands)


def test_start_file_edit_edit_symbol_requires_symbol_name():
    with pytest.raises(FunctionCallValidationError, match='symbol_name'):
        _handle_start_file_edit_tool(
            {
                'operation': 'edit_symbol',
                'path': 'app.py',
                'security_risk': 'LOW',
            }
        )


def test_start_file_edit_required_metadata_validation_runs():
    with pytest.raises(FunctionCallValidationError, match='start_line'):
        _handle_start_file_edit_tool(
            {
                'operation': 'replace_range',
                'path': 'app.py',
                'end_line': 4,
                'security_risk': 'LOW',
            }
        )


def test_start_file_edit_accepts_edit_symbols_operation():
    action = _handle_start_file_edit_tool(
        {
            'operation': 'edit_symbols',
            'path': 'app.py',
            'symbol_names': ['a', 'b'],
            'security_risk': 'LOW',
        }
    )
    assert isinstance(action, StartFileEditAction)
    assert action.operation == 'edit_symbols'


def test_start_file_edit_accepts_multi_edit_without_path():
    action = _handle_start_file_edit_tool(
        {
            'operation': 'multi_edit',
            'batch_operations': [
                {
                    'path': 'a.py',
                    'operation': 'replace_range',
                    'start_line': 1,
                    'end_line': 1,
                }
            ],
            'security_risk': 'LOW',
        }
    )
    assert isinstance(action, StartFileEditAction)
    assert action.path == '<batch>'
    assert action.operation == 'multi_edit'


def test_start_file_edit_multi_edit_requires_batch_operations():
    with pytest.raises(FunctionCallValidationError, match='batch_operations'):
        _handle_start_file_edit_tool(
            {
                'operation': 'multi_edit',
                'security_risk': 'LOW',
            }
        )


def test_start_file_edit_runtime_creates_transaction(tmp_path):
    action = StartFileEditAction(
        path='app.py',
        operation='replace_range',
        metadata={'security_risk': 'LOW', 'start_line': 1, 'end_line': 2},
        session_id='runtime_create',
    )
    runtime = SimpleNamespace(workspace_root=tmp_path)
    obs = start_file_edit_transaction(runtime, action)
    txn = get_transaction_store().get_active_transaction('runtime_create')
    assert obs.tool_result['status'] == 'editor_mode_required'
    assert txn is not None
    assert txn.transaction_id == obs.tool_result['transaction_id']
    get_transaction_store().clear_active_transaction('runtime_create')
