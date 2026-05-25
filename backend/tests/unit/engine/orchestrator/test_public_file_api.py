"""Public model-facing file API handler tests."""

from __future__ import annotations

import json

import pytest

from backend.core.errors import FunctionCallValidationError, ToolExecutionError
from backend.engine.function_calling import (
    _handle_create_tool,
    _handle_edit_symbols_tool,
    _handle_find_symbols_tool,
    _handle_multi_edit_command,
    _handle_multiedit_tool,
    _handle_read_tool,
    _handle_replace_string_tool,
)
from backend.ledger.action import AgentThinkAction, FileEditAction, FileReadAction


def _use_tmp_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import backend.core.workspace_resolution as workspace_resolution

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        workspace_resolution,
        'require_effective_workspace_root',
        lambda: tmp_path,
    )


def _payload(action: AgentThinkAction) -> dict:
    _, _, raw = action.thought.partition('\n')
    return json.loads(raw)


def test_read_file_and_range_return_file_read_actions(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'a.txt').write_text('one\ntwo\nthree\n', encoding='utf-8')

    file_action = _handle_read_tool(
        {'type': 'file', 'path': 'a.txt', 'security_risk': 'LOW'}
    )
    range_action = _handle_read_tool(
        {
            'type': 'range',
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


def test_read_symbols_auto_resolves_unique_symbol(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'mod.py').write_text('def login():\n    return True\n', encoding='utf-8')

    action = _handle_read_tool(
        {
            'type': 'symbols',
            'symbols': [{'symbol_name': 'login'}],
            'security_risk': 'LOW',
        }
    )
    payload = _payload(action)
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

    candidates = _payload(
        _handle_find_symbols_tool(
            {'query': 'run', 'security_risk': 'LOW'}
        )
    )
    ambiguous = _payload(
        _handle_read_tool(
            {
                'type': 'symbols',
                'symbols': [{'symbol_name': 'run'}],
                'security_risk': 'LOW',
            }
        )
    )

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

    payload = _payload(
        _handle_read_tool(
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
    )

    assert [item['status'] for item in payload['results']] == [
        'resolved',
        'ambiguous',
        'not_found',
    ]
    assert payload['results'][0]['content'] == 'def authenticate_user():\n    return True\n'
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

    payload = _payload(
        _handle_read_tool(
            {
                'type': 'symbols',
                'symbols': [{'qualified_name': 'UserService.login'}],
                'security_risk': 'LOW',
            }
        )
    )
    result = payload['results'][0]

    assert result['status'] == 'resolved'
    assert result['qualified_name'] == 'UserService.login'
    assert result['symbol_kind'] == 'method'
    assert 'return "user"' in result['content']


def test_create_file_public_action_never_overwrites_and_rejects_serialized(
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
    assert action.overwrite_existing is False

    with pytest.raises(FunctionCallValidationError, match='File already exists'):
        _handle_create_tool(
            {
                'type': 'file',
                'path': 'existing.py',
                'content': 'print("new")\n',
                'security_risk': 'LOW',
            }
        )

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
    (tmp_path / 'mod.py').write_text('def login():\n    return True\n', encoding='utf-8')

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
    assert replace.expected_file_hash


def test_edit_symbols_replaces_one_or_more_symbols(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'mod.py').write_text(
        'def a():\n    return 1\n\n'
        'def b():\n    return 2\n',
        encoding='utf-8',
    )

    action = _handle_edit_symbols_tool(
        {
            'path': 'mod.py',
            'edits': [
                {'symbol_name': 'a', 'new_content': 'def a():\n    return 10\n'},
                {'symbol_name': 'b', 'new_content': 'def b():\n    return 20\n'},
            ],
            'security_risk': 'LOW',
        }
    )

    assert isinstance(action, FileEditAction)
    assert action.command == 'multi_edit'
    assert action.structured_payload == {
        'file_edits': [
            {
                'path': 'mod.py',
                'operation': 'symbol_body_replacement',
                'start_line': 4,
                'end_line': 5,
                'content': 'def b():\n    return 20\n',
            },
            {
                'path': 'mod.py',
                'operation': 'symbol_body_replacement',
                'start_line': 1,
                'end_line': 2,
                'content': 'def a():\n    return 10\n',
            },
        ]
    }


def test_edit_symbols_rejects_ambiguous_write_target(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'mod.py').write_text(
        'class A:\n    def run(self):\n        return 1\n\n'
        'class B:\n    def run(self):\n        return 2\n',
        encoding='utf-8',
    )

    with pytest.raises(FunctionCallValidationError, match='ambiguous'):
        _handle_edit_symbols_tool(
            {
                'path': 'mod.py',
                'edits': [
                    {
                        'symbol_name': 'run',
                        'new_content': 'def run(self):\n    return 3\n',
                    }
                ],
                'security_risk': 'LOW',
            }
        )


def test_edit_symbols_accepts_path_qualified_name_and_kind(monkeypatch, tmp_path):
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

    action = _handle_edit_symbols_tool(
        {
            'edits': [
                {
                    'path': 'auth.py',
                    'qualified_name': 'AdminService.login',
                    'symbol_kind': 'method',
                    'new_content': '    def login(self):\n        return "root"\n',
                }
            ],
            'security_risk': 'LOW',
        }
    )

    assert action.command == 'multi_edit'
    assert action.structured_payload == {
        'file_edits': [
            {
                'path': 'auth.py',
                'operation': 'symbol_body_replacement',
                'start_line': 6,
                'end_line': 7,
                'content': '    def login(self):\n        return "root"\n',
            }
        ]
    }


def test_edit_symbols_rejects_serialized_payload(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'mod.py').write_text('def a():\n    return 1\n', encoding='utf-8')

    with pytest.raises(FunctionCallValidationError, match='CONTENT_APPEARS_SERIALIZED'):
        _handle_edit_symbols_tool(
            {
                'path': 'mod.py',
                'edits': [{'symbol_name': 'a', 'new_content': '"def a():\\n    return 2\\n"'}],
                'security_risk': 'LOW',
            }
        )


def test_multiedit_public_action_normalizes_new_public_operations_and_guards_content(
    monkeypatch, tmp_path
):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'mod.py').write_text('def login():\n    return True\n', encoding='utf-8')

    action = _handle_multiedit_tool(
        {
            'operations': [
                {'command': 'create', 'type': 'file', 'path': 'a.py', 'content': 'A = 1\n'},
                {
                    'command': 'create',
                    'type': 'symbol',
                    'path': 'mod.py',
                    'target_symbol': 'login',
                    'position': 'after',
                    'content': 'def logout():\n    return True\n',
                },
                {
                    'command': 'replace_string',
                    'path': 'README.md',
                    'old_string': 'old',
                    'new_string': 'new',
                },
                {
                    'command': 'edit_symbols',
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
        'path': 'a.py',
        'operation': 'create_file',
        'content': 'A = 1\n',
    }
    assert action.structured_payload['file_edits'][1]['operation'] == 'create_symbol'
    assert action.structured_payload['file_edits'][2]['operation'] == 'replace_string'
    assert action.structured_payload['file_edits'][3]['operation'] == 'symbol_body_replacement'

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

    with pytest.raises(FunctionCallValidationError, match='Use create, replace_string, or edit_symbols'):
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
