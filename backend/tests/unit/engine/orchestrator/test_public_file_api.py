"""Public model-facing file API handler tests."""

from __future__ import annotations

import json

import pytest

from backend.core.errors import FunctionCallValidationError, ToolExecutionError
from backend.engine.function_calling import (
    _handle_create_tool,
    _handle_edit_symbols_tool,
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


def test_read_symbol_auto_resolves_unique_symbol(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'mod.py').write_text('def login():\n    return True\n', encoding='utf-8')

    action = _handle_read_tool(
        {'type': 'symbol', 'symbol_name': 'login', 'security_risk': 'LOW'}
    )
    payload = _payload(action)

    assert payload['status'] == 'ok'
    assert payload['name'] == 'login'
    assert payload['path'] == 'mod.py'
    assert payload['content'] == 'def login():\n    return True\n'


def test_read_symbols_returns_candidates_and_symbol_read_reports_ambiguity(
    monkeypatch, tmp_path
):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'mod.py').write_text(
        'class A:\n    def run(self):\n        return 1\n\n'
        'class B:\n    def run(self):\n        return 2\n',
        encoding='utf-8',
    )

    candidates = _payload(
        _handle_read_tool(
            {'type': 'symbols', 'query': 'run', 'security_risk': 'LOW'}
        )
    )
    ambiguous = _payload(
        _handle_read_tool(
            {'type': 'symbol', 'symbol_name': 'run', 'security_risk': 'LOW'}
        )
    )

    assert candidates['type'] == 'symbols'
    assert len(candidates['candidates']) == 2
    assert ambiguous['status'] == 'ambiguous'
    assert len(ambiguous['candidates']) == 2


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
                'command': 'replace_range',
                'start_line': 4,
                'end_line': 5,
                'new_code': 'def b():\n    return 20\n',
            },
            {
                'path': 'mod.py',
                'command': 'replace_range',
                'start_line': 1,
                'end_line': 2,
                'new_code': 'def a():\n    return 10\n',
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
        'command': 'create_file',
        'content': 'A = 1\n',
    }
    assert action.structured_payload['file_edits'][1]['command'] == 'create_symbol'
    assert action.structured_payload['file_edits'][2]['command'] == 'replace_string'
    assert action.structured_payload['file_edits'][3]['command'] == 'replace_range'

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
                        'command': 'replace_string',
                        'old_string': 'A = 1\n',
                        'new_string': 'A = 2\n',
                    },
                    {
                        'path': 'b.py',
                        'command': 'replace_string',
                        'old_string': 'missing',
                        'new_string': 'B = 2\n',
                    },
                ]
            },
        )

    assert (tmp_path / 'a.py').read_text(encoding='utf-8') == 'A = 1\n'
    assert (tmp_path / 'b.py').read_text(encoding='utf-8') == 'B = 1\n'
