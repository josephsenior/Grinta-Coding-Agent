"""Public model-facing file API handler tests."""

from __future__ import annotations

import json

import pytest

from backend.core.errors import FunctionCallValidationError, ToolExecutionError
from backend.engine.function_calling.dispatch import (
    _handle_create_file_tool,
    _handle_find_symbols_tool,
    _handle_multi_edit_command,
    _handle_multiedit_tool,
    _handle_read_file_tool,
    _handle_read_symbols_tool,
    _handle_replace_string_tool,
)
from backend.engine.tools._file_edits import execute_find_symbols, execute_read_symbols
from backend.ledger.action import (
    FileEditAction,
    FileReadAction,
    FindSymbolsAction,
    ReadSymbolsAction,
)
from backend.ledger.observation import ErrorObservation


def _use_tmp_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import backend.core.workspace_resolution as workspace_resolution

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        workspace_resolution,
        'require_effective_workspace_root',
        lambda: tmp_path,
    )


def _payload(event: object) -> dict:
    content = getattr(event, 'content', '')
    if content:
        return json.loads(str(content))
    tool_result = getattr(event, 'tool_result', None)
    if isinstance(tool_result, dict):
        return dict(tool_result)
    return {}


def _read_symbols_result(action: ReadSymbolsAction) -> dict | ErrorObservation:
    obs = execute_read_symbols(action)
    if isinstance(obs, ErrorObservation):
        return obs
    return _payload(obs)


def test_read_file_and_range_return_file_read_actions(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'a.txt').write_text('one\ntwo\nthree\n', encoding='utf-8')

    file_action = _handle_read_file_tool(
        {'path': 'a.txt', 'security_risk': 'LOW'}
    )
    range_action = _handle_read_file_tool(
        {
            'path': 'a.txt',
            'start_line': 2,
            'end_line': 3,
            'security_risk': 'LOW',
        }
    )

    assert isinstance(file_action, FileReadAction)
    assert file_action.path == 'a.txt'
    assert isinstance(range_action, FileReadAction)
    assert range_action.path == 'a.txt'
    assert range_action.view_range == [2, 3]


def test_read_file_requires_path(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)

    with pytest.raises(FunctionCallValidationError, match='path'):
        _handle_read_file_tool({'security_risk': 'LOW'})


def test_read_file_line_range_requires_both_bounds(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'a.txt').write_text('one\ntwo\n', encoding='utf-8')

    with pytest.raises(
        FunctionCallValidationError, match='both start_line and end_line'
    ):
        _handle_read_file_tool(
            {
                'path': 'a.txt',
                'start_line': 1,
                'security_risk': 'LOW',
            }
        )


def test_read_symbols_accepts_legacy_flat_qualified_name(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'mod.py').write_text(
        'def login():\n    return True\n', encoding='utf-8'
    )

    action = _handle_read_symbols_tool(
        {
            'qualified_name': 'login',
            'security_risk': 'LOW',
        }
    )
    assert isinstance(action, ReadSymbolsAction)
    assert action.targets == [{'qualified_name': 'login'}]


def test_read_symbols_requires_symbol_target(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)

    with pytest.raises(FunctionCallValidationError, match='symbols\\[\\]'):
        _handle_read_symbols_tool(
            {
                'security_risk': 'LOW',
            }
        )


def test_read_symbols_auto_resolves_unique_symbol(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'mod.py').write_text(
        'def login():\n    return True\n', encoding='utf-8'
    )

    action = _handle_read_symbols_tool(
        {
            'symbols': [{'symbol_name': 'login'}],
            'security_risk': 'LOW',
        }
    )
    assert isinstance(action, ReadSymbolsAction)
    payload = _payload(execute_read_symbols(action))
    result = payload['results'][0]

    assert payload['status'] == 'ok'
    assert result['status'] == 'resolved'
    assert result['name'] == 'login'
    assert result['path'] == 'mod.py'
    assert result['content'] == 'def login():\n    return True\n'


def test_find_symbols_discovers_candidates_and_read_symbols_reports_ambiguity(
    monkeypatch, tmp_path
):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'mod.py').write_text(
        'class A:\n    def run(self):\n        return 1\n\n'
        'class B:\n    def run(self):\n        return 2\n',
        encoding='utf-8',
    )

    find_action = _handle_find_symbols_tool({'query': 'run', 'security_risk': 'LOW'})
    assert isinstance(find_action, FindSymbolsAction)
    candidates = _payload(execute_find_symbols(find_action))
    read_action = _handle_read_symbols_tool(
        {
            'symbols': [{'symbol_name': 'run'}],
            'security_risk': 'LOW',
        }
    )
    assert isinstance(read_action, ReadSymbolsAction)
    ambiguous = _read_symbols_result(read_action)

    assert candidates['type'] == 'symbols'
    assert len(candidates['candidates']) == 2
    assert {item['qualified_name'] for item in candidates['candidates']} == {
        'A.run',
        'B.run',
    }
    assert {item['symbol_kind'] for item in candidates['candidates']} == {'method'}
    assert all('content' not in item for item in candidates['candidates'])
    assert isinstance(ambiguous, ErrorObservation)
    assert 'ambiguous' in ambiguous.content
    assert ambiguous.tool_result['error_code'] == 'SYMBOL_AMBIGUOUS'
    assert len(ambiguous.tool_result.get('candidates') or []) == 2


def test_read_symbols_resolves_each_requested_symbol_independently(
    monkeypatch, tmp_path
):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'auth.py').write_text(
        'def authenticate_user():\n    return True\n\n'
        'class A:\n    def validate(self):\n        return 1\n\n'
        'class B:\n    def validate(self):\n        return 2\n',
        encoding='utf-8',
    )

    action = _handle_read_symbols_tool(
        {
            'symbols': [
                {'symbol_name': 'authenticate_user'},
                {'symbol_name': 'validate'},
                {'symbol_name': 'MissingService'},
            ],
            'security_risk': 'LOW',
        }
    )
    assert isinstance(action, ReadSymbolsAction)
    result = _read_symbols_result(action)

    assert isinstance(result, ErrorObservation)
    assert '2 of 3 targets could not be resolved' in result.content
    assert result.tool_result['failed_count'] == 2
    assert result.tool_result['resolved_count'] == 1
    assert 'validate' in result.content
    assert 'MissingService' in result.content


def test_read_symbols_accepts_qualified_names_without_path(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'auth.py').write_text(
        'class UserService:\n'
        '    def login(self):\n'
        '        return "user"\n\n'
        'class AdminService:\n'
        '    def login(self):\n'
        '        return "admin"\n',
        encoding='utf-8',
    )

    action = _handle_read_symbols_tool(
        {
            'symbols': [{'qualified_name': 'UserService.login'}],
            'security_risk': 'LOW',
        }
    )
    assert isinstance(action, ReadSymbolsAction)
    payload = _payload(execute_read_symbols(action))
    result = payload['results'][0]

    assert result['status'] == 'resolved'
    assert result['qualified_name'] == 'UserService.login'
    assert result['symbol_kind'] == 'method'
    assert 'return "user"' in result['content']


def test_read_symbol_infers_symbols_from_symbols_array(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'mod.py').write_text(
        'def login():\n    return True\n', encoding='utf-8'
    )

    action = _handle_read_symbols_tool(
        {
            'symbols': [{'symbol_name': 'login'}],
            'security_risk': 'LOW',
        }
    )

    assert isinstance(action, ReadSymbolsAction)


def test_read_symbol_infers_from_flat_qualified_name(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'mod.py').write_text(
        'def login():\n    return True\n', encoding='utf-8'
    )

    action = _handle_read_symbols_tool(
        {
            'qualified_name': 'login',
            'security_risk': 'LOW',
        }
    )

    assert isinstance(action, ReadSymbolsAction)
    payload = _payload(execute_read_symbols(action))
    assert payload['results'][0]['status'] == 'resolved'


def test_create_file_public_action_passes_through_and_rejects_serialized(
    monkeypatch, tmp_path
):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'existing.py').write_text('print("old")\n', encoding='utf-8')

    action = _handle_create_file_tool(
        {
            'path': 'new.py',
            'content': 'print("ok")\n',
            'security_risk': 'LOW',
        }
    )

    assert isinstance(action, FileEditAction)
    assert action.command == 'create_file'
    assert action.file_text == 'print("ok")\n'
    assert action.overwrite_existing is False

    existing_action = _handle_create_file_tool(
        {
            'path': 'existing.py',
            'content': 'print("new")\n',
            'security_risk': 'LOW',
        }
    )
    assert isinstance(existing_action, FileEditAction)
    assert existing_action.command == 'create_file'
    assert existing_action.overwrite_existing is False

    with pytest.raises(FunctionCallValidationError, match='CONTENT_APPEARS_SERIALIZED'):
        _handle_create_file_tool(
            {
                'path': 'bad.py',
                'content': '"print(\\"bad\\")\\n"',
                'security_risk': 'LOW',
            }
        )


def test_replace_string_public_action_supports_replace_add_and_delete(
    monkeypatch, tmp_path
):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'README.md').write_text('## Usage\n\nold\nobsolete\n', encoding='utf-8')

    replace = _handle_replace_string_tool(
        {
            'path': 'README.md',
            'old_string': 'old',
            'new_string': 'new',
            'security_risk': 'LOW',
        }
    )
    add = _handle_replace_string_tool(
        {
            'path': 'README.md',
            'old_string': '## Usage\n',
            'new_string': '## Usage\n\nExample:\n...',
            'security_risk': 'LOW',
        }
    )
    delete = _handle_replace_string_tool(
        {
            'path': 'README.md',
            'old_string': 'obsolete\n',
            'new_string': '',
            'security_risk': 'LOW',
        }
    )

    assert replace.command == 'replace_string'
    assert replace.old_string == 'old'
    assert replace.new_str == 'new'
    assert add.new_str == '## Usage\n\nExample:\n...'
    assert delete.new_str == ''
    assert replace.replace_all is False


def test_multiedit_public_action_normalizes_supported_operations_and_guards_content(
    monkeypatch, tmp_path
):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'mod.py').write_text(
        'def login():\n    return True\n', encoding='utf-8'
    )
    (tmp_path / 'README.md').write_text('old\n', encoding='utf-8')

    action = _handle_multiedit_tool(
        {
            'operations': [
                {
                    'path': 'README.md',
                    'old_string': 'old',
                    'new_string': 'new',
                },
                {
                    'path': 'mod.py',
                    'old_string': 'def login():\n    return True\n',
                    'new_string': 'def login():\n    return False\n',
                },
            ],
            'security_risk': 'LOW',
        }
    )

    assert isinstance(action, FileEditAction)
    assert action.command == 'multi_edit'
    assert action.structured_payload['file_edits'][0] == {
        'operation': 'replace_string',
        'path': 'README.md',
        'old_string': 'old',
        'new_string': 'new',
        'replace_all': False,
    }
    assert action.structured_payload['file_edits'][1] == {
        'operation': 'replace_string',
        'path': 'mod.py',
        'old_string': 'def login():\n    return True\n',
        'new_string': 'def login():\n    return False\n',
        'replace_all': False,
    }

    with pytest.raises(FunctionCallValidationError, match='CONTENT_APPEARS_SERIALIZED'):
        _handle_multiedit_tool(
            {
                'operations': [
                    {
                        'path': 'a.py',
                        'old_string': 'A = 1\n',
                        'new_string': '"A = 2\\n"',
                    }
                ],
                'security_risk': 'LOW',
            }
        )


def test_multiedit_rejects_replace_string_without_path(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)

    with pytest.raises(
        FunctionCallValidationError, match='replace_string requires path'
    ):
        _handle_multiedit_tool(
            {
                'operations': [
                    {
                        'command': 'replace_string',
                        'old_string': 'old',
                        'new_string': 'new',
                    }
                ],
                'security_risk': 'LOW',
            }
        )


def test_multiedit_schema_requires_path_on_operations() -> None:
    from backend.engine.tools.native_file_tools import create_multiedit_tool

    params = create_multiedit_tool()['function']['parameters']
    items = params['properties']['operations']['items']
    assert items['required'] == ['path', 'old_string', 'new_string']


def test_multiedit_commits_no_changes_when_one_operation_fails(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'a.py').write_text('A = 1\n', encoding='utf-8')
    (tmp_path / 'b.py').write_text('B = 1\n', encoding='utf-8')

    with pytest.raises(ToolExecutionError) as exc_info:
        _handle_multi_edit_command(
            '.',
            {
                'file_edits': [
                    {
                        'path': 'a.py',
                        'operation': 'replace_string',
                        'old_string': 'A = 1\n',
                        'new_string': 'A = 2\n',
                    },
                    {
                        'path': 'b.py',
                        'operation': 'replace_string',
                        'old_string': 'missing',
                        'new_string': 'B = 2\n',
                    },
                ]
            },
        )

    exc = exc_info.value
    assert 'replace_string failed: old_string not found exactly.' in str(exc)
    assert 'File: b.py' in str(exc)
    assert 'Op index: 1 (2/2)' in str(exc)
    assert exc.context['error_code'] == 'OLD_STRING_NOT_FOUND'
    assert 'missing' not in str(exc)

    assert (tmp_path / 'a.py').read_text(encoding='utf-8') == 'A = 1\n'
    assert (tmp_path / 'b.py').read_text(encoding='utf-8') == 'B = 1\n'
