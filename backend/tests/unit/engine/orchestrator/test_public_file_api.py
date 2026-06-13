"""Public model-facing file API handler tests."""

from __future__ import annotations

import json

import pytest

from backend.core.errors import FunctionCallValidationError, ToolExecutionError
from backend.engine.function_calling import (
    _handle_create_tool,
    _handle_edit_symbol_tool,
    _handle_find_symbols_tool,
    _handle_multi_edit_command,
    _handle_multiedit_tool,
    _handle_read_tool,
    _handle_replace_string_tool,
)
from backend.engine.tools._file_edits import execute_find_symbols, execute_read_symbols
from backend.ledger.action import (
    AgentThinkAction,
    FileEditAction,
    FileReadAction,
    FindSymbolsAction,
    ReadSymbolsAction,
)


def _use_tmp_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import backend.core.workspace_resolution as workspace_resolution

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        workspace_resolution,
        'require_effective_workspace_root',
        lambda: tmp_path,
    )


def _payload(event: object) -> dict:
    tool_result = getattr(event, 'tool_result', None)
    if isinstance(tool_result, dict):
        return dict(tool_result)
    content = getattr(event, 'content', '')
    return json.loads(str(content))


def test_read_file_and_range_return_file_read_actions(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'a.txt').write_text('one\ntwo\nthree\n', encoding='utf-8')

    file_action = _handle_read_tool(
        {'type': 'file', 'path': 'a.txt', 'security_risk': 'LOW'}
    )
    range_action = _handle_read_tool(
        {
            'type': 'file',
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


def test_read_rejects_legacy_range_type(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'a.txt').write_text('one\n', encoding='utf-8')

    with pytest.raises(FunctionCallValidationError, match='type=range was removed'):
        _handle_read_tool(
            {
                'type': 'range',
                'path': 'a.txt',
                'start_line': 1,
                'end_line': 1,
                'security_risk': 'LOW',
            }
        )


def test_read_symbols_requires_symbols_array(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)

    with pytest.raises(FunctionCallValidationError, match='symbols\\[\\]'):
        _handle_read_tool(
            {
                'type': 'symbols',
                'qualified_name': 'login',
                'security_risk': 'LOW',
            }
        )


def test_read_file_range_requires_both_line_bounds(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'a.txt').write_text('one\ntwo\n', encoding='utf-8')

    with pytest.raises(
        FunctionCallValidationError, match='both start_line and end_line'
    ):
        _handle_read_tool(
            {
                'type': 'file',
                'path': 'a.txt',
                'start_line': 1,
                'security_risk': 'LOW',
            }
        )


def test_read_symbols_auto_resolves_unique_symbol(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'mod.py').write_text(
        'def login():\n    return True\n', encoding='utf-8'
    )

    action = _handle_read_tool(
        {
            'type': 'symbols',
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
    read_action = _handle_read_tool(
        {
            'type': 'symbols',
            'symbols': [{'symbol_name': 'run'}],
            'security_risk': 'LOW',
        }
    )
    assert isinstance(read_action, ReadSymbolsAction)
    ambiguous = _payload(execute_read_symbols(read_action))

    assert candidates['type'] == 'symbols'
    assert len(candidates['candidates']) == 2
    assert {item['qualified_name'] for item in candidates['candidates']} == {
        'A.run',
        'B.run',
    }
    assert {item['symbol_kind'] for item in candidates['candidates']} == {'method'}
    assert all('content' not in item for item in candidates['candidates'])
    assert ambiguous['results'][0]['status'] == 'ambiguous'
    assert len(ambiguous['results'][0]['candidates']) == 2
    assert 'content' not in ambiguous['results'][0]


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

    action = _handle_read_tool(
        {
            'type': 'symbols',
            'symbols': [
                {'symbol_name': 'authenticate_user'},
                {'symbol_name': 'validate'},
                {'symbol_name': 'MissingService'},
            ],
            'security_risk': 'LOW',
        }
    )
    assert isinstance(action, ReadSymbolsAction)
    payload = _payload(execute_read_symbols(action))

    assert [item['status'] for item in payload['results']] == [
        'resolved',
        'ambiguous',
        'not_found',
    ]
    assert (
        payload['results'][0]['content']
        == 'def authenticate_user():\n    return True\n'
    )
    assert len(payload['results'][1]['candidates']) == 2
    assert "Symbol 'MissingService' was not found." == payload['results'][2]['message']


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

    action = _handle_read_tool(
        {
            'type': 'symbols',
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


def test_create_file_public_action_overwrites_by_default_and_rejects_serialized(
    monkeypatch, tmp_path
):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'existing.py').write_text('print("old")\n', encoding='utf-8')

    action = _handle_create_tool(
        {
            'type': 'file',
            'path': 'new.py',
            'content': 'print("ok")\n',
            'security_risk': 'LOW',
        }
    )

    assert isinstance(action, FileEditAction)
    assert action.command == 'create_file'
    assert action.file_text == 'print("ok")\n'
    assert action.overwrite_existing is True

    existing_action = _handle_create_tool(
        {
            'type': 'file',
            'path': 'existing.py',
            'content': 'print("new")\n',
            'security_risk': 'LOW',
        }
    )
    # File existence pre-check: returns soft guidance instead of overwriting
    assert isinstance(existing_action, AgentThinkAction)
    assert 'already exists' in existing_action.thought
    assert 'replace_string' in existing_action.thought

    with pytest.raises(FunctionCallValidationError, match='CONTENT_APPEARS_SERIALIZED'):
        _handle_create_tool(
            {
                'type': 'file',
                'path': 'bad.py',
                'content': '"print(\\"bad\\")\\n"',
                'security_risk': 'LOW',
            }
        )


def test_create_symbol_adds_a_new_symbol(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'mod.py').write_text(
        'def login():\n    return True\n', encoding='utf-8'
    )

    action = _handle_create_tool(
        {
            'type': 'symbol',
            'path': 'mod.py',
            'target_symbol': 'login',
            'position': 'after',
            'content': 'def logout():\n    return True\n',
            'security_risk': 'LOW',
        }
    )

    assert isinstance(action, FileEditAction)
    assert action.command == 'insert_text'
    assert action.insert_line == 3
    assert action.new_str == 'def logout():\n    return True\n'


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


def test_edit_symbol_normalizes_to_deferred_multi_edit(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'mod.py').write_text('def a():\n    return 1\n', encoding='utf-8')

    action = _handle_edit_symbol_tool(
        {
            'path': 'mod.py',
            'symbol_name': 'a',
            'new_content': 'def a():\n    return 10\n',
            'security_risk': 'LOW',
        }
    )

    assert isinstance(action, FileEditAction)
    assert action.command == 'multi_edit'
    assert action.structured_payload == {
        'file_edits': [
            {
                'path': 'mod.py',
                'operation': 'edit_symbol_deferred',
                'edits': [
                    {
                        'symbol_name': 'a',
                        'new_content': 'def a():\n    return 10\n',
                    }
                ],
            }
        ]
    }


def test_edit_symbol_rejects_legacy_edits_array(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'mod.py').write_text('def a():\n    return 1\n', encoding='utf-8')

    with pytest.raises(FunctionCallValidationError, match='use multiedit'):
        _handle_edit_symbol_tool(
            {
                'path': 'mod.py',
                'edits': [
                    {'symbol_name': 'a', 'new_content': 'def a():\n    return 10\n'},
                ],
                'security_risk': 'LOW',
            }
        )


def test_edit_symbol_rejects_ambiguous_write_target(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'mod.py').write_text(
        'class A:\n    def run(self):\n        return 1\n\n'
        'class B:\n    def run(self):\n        return 2\n',
        encoding='utf-8',
    )

    with pytest.raises(FunctionCallValidationError, match='ambiguous'):
        _handle_multi_edit_command(
            '.',
            {
                'file_edits': [
                    {
                        'path': 'mod.py',
                        'operation': 'edit_symbol_deferred',
                        'edits': [
                            {
                                'symbol_name': 'run',
                                'new_content': 'def run(self):\n    return 3\n',
                            }
                        ],
                    }
                ]
            },
        )


def test_edit_symbol_accepts_path_qualified_name_and_kind(monkeypatch, tmp_path):
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

    action = _handle_edit_symbol_tool(
        {
            'path': 'auth.py',
            'qualified_name': 'AdminService.login',
            'symbol_kind': 'method',
            'new_content': '    def login(self):\n        return "root"\n',
            'security_risk': 'LOW',
        }
    )

    assert action.command == 'multi_edit'
    assert action.structured_payload == {
        'file_edits': [
            {
                'path': 'auth.py',
                'operation': 'edit_symbol_deferred',
                'edits': [
                    {
                        'qualified_name': 'AdminService.login',
                        'symbol_kind': 'method',
                        'new_content': '    def login(self):\n        return "root"\n',
                    }
                ],
            }
        ]
    }


def test_edit_symbol_rejects_serialized_payload(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'mod.py').write_text('def a():\n    return 1\n', encoding='utf-8')

    with pytest.raises(FunctionCallValidationError, match='CONTENT_APPEARS_SERIALIZED'):
        _handle_edit_symbol_tool(
            {
                'path': 'mod.py',
                'symbol_name': 'a',
                'new_content': '"def a():\\n    return 2\\n"',
                'security_risk': 'LOW',
            }
        )


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
                    'command': 'replace_string',
                    'path': 'README.md',
                    'old_string': 'old',
                    'new_string': 'new',
                },
                {
                    'command': 'edit_symbol',
                    'path': 'mod.py',
                    'edits': [
                        {
                            'symbol_name': 'login',
                            'new_content': 'def login():\n    return False\n',
                        }
                    ],
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
    assert (
        action.structured_payload['file_edits'][1]['operation']
        == 'edit_symbol_deferred'
    )
    assert action.structured_payload['file_edits'][1]['path'] == 'mod.py'
    assert action.structured_payload['file_edits'][1]['edits'][0]['symbol_name'] == 'login'

    with pytest.raises(FunctionCallValidationError, match='CONTENT_APPEARS_SERIALIZED'):
        _handle_multiedit_tool(
            {
                'operations': [
                    {
                        'command': 'replace_string',
                        'path': 'a.py',
                        'old_string': 'A = 1\n',
                        'new_string': '"A = 2\\n"',
                    }
                ],
                'security_risk': 'LOW',
            }
        )


def test_multiedit_rejects_old_public_aliases(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)

    with pytest.raises(
        FunctionCallValidationError, match='Use replace_string or edit_symbol'
    ):
        _handle_multiedit_tool(
            {
                'operations': [
                    {'command': 'create_file', 'path': 'a.py', 'content': 'A = 1\n'}
                ],
                'security_risk': 'LOW',
            }
        )


def test_multiedit_commits_no_changes_when_one_operation_fails(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'a.py').write_text('A = 1\n', encoding='utf-8')
    (tmp_path / 'b.py').write_text('B = 1\n', encoding='utf-8')

    with pytest.raises(ToolExecutionError):
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

    assert (tmp_path / 'a.py').read_text(encoding='utf-8') == 'A = 1\n'
    assert (tmp_path / 'b.py').read_text(encoding='utf-8') == 'B = 1\n'
