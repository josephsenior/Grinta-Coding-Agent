"""Public model-facing file API handler tests."""

from __future__ import annotations

import json

import pytest

from backend.core.errors import FunctionCallValidationError
from backend.engine.function_calling import (
    _handle_create_file_tool,
    _handle_edit_symbols_tool,
    _handle_find_symbols_tool,
    _handle_insert_symbol_tool,
    _handle_multiedit_tool,
    _handle_read_range_tool,
    _handle_read_symbol_tool,
    _handle_replace_string_tool,
    _handle_replace_symbol_tool,
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


def test_read_range_returns_file_read_action(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'a.txt').write_text('one\ntwo\nthree\n', encoding='utf-8')

    action = _handle_read_range_tool(
        {
            'path': 'a.txt',
            'start_line': 2,
            'end_line': 3,
            'security_risk': 'LOW',
        }
    )

    assert isinstance(action, FileReadAction)
    assert action.path == 'a.txt'
    assert action.view_range == [2, 3]


def test_create_file_public_action_never_overwrites_and_rejects_serialized(
    monkeypatch, tmp_path
):
    _use_tmp_workspace(monkeypatch, tmp_path)

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

    with pytest.raises(FunctionCallValidationError, match='CONTENT_APPEARS_SERIALIZED'):
        _handle_create_file_tool(
            {
                'path': 'bad.py',
                'content': '"print(\\"bad\\")\\n"',
                'security_risk': 'LOW',
            }
        )


def test_replace_string_public_action(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'README.md').write_text('## Usage\n\nold\n', encoding='utf-8')

    action = _handle_replace_string_tool(
        {
            'path': 'README.md',
            'old_string': '## Usage\n',
            'new_string': '## Usage\n\nExample:\n...',
            'security_risk': 'LOW',
        }
    )

    assert isinstance(action, FileEditAction)
    assert action.command == 'replace_string'
    assert action.old_string == '## Usage\n'
    assert action.new_str == '## Usage\n\nExample:\n...'
    assert action.replace_all is False
    assert action.expected_file_hash


def test_symbol_read_replace_and_insert_public_actions(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    source = tmp_path / 'mod.py'
    source.write_text('def login():\n    return True\n', encoding='utf-8')

    found = _payload(
        _handle_find_symbols_tool(
            {'path': 'mod.py', 'query': 'login', 'security_risk': 'LOW'}
        )
    )
    assert found['candidates'][0]['name'] == 'login'

    read = _payload(
        _handle_read_symbol_tool(
            {'path': 'mod.py', 'symbol_name': 'login', 'security_risk': 'LOW'}
        )
    )
    assert read['content'] == 'def login():\n    return True\n'

    replacement = _handle_replace_symbol_tool(
        {
            'path': 'mod.py',
            'symbol_name': 'login',
            'new_content': 'def login():\n    return False\n',
            'security_risk': 'LOW',
        }
    )
    assert isinstance(replacement, FileEditAction)
    assert replacement.command == 'edit'
    assert replacement.edit_mode == 'range'
    assert replacement.start_line == 1
    assert replacement.end_line == 2

    insertion = _handle_insert_symbol_tool(
        {
            'path': 'mod.py',
            'target_symbol': 'login',
            'position': 'after',
            'content': 'def logout():\n    return True\n',
            'security_risk': 'LOW',
        }
    )
    assert isinstance(insertion, FileEditAction)
    assert insertion.command == 'insert_text'
    assert insertion.insert_line == 3


def test_replace_symbol_rejects_ambiguous_target(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'mod.py').write_text(
        'class A:\n    def run(self):\n        return 1\n\n'
        'class B:\n    def run(self):\n        return 2\n',
        encoding='utf-8',
    )

    with pytest.raises(FunctionCallValidationError, match='ambiguous'):
        _handle_replace_symbol_tool(
            {
                'path': 'mod.py',
                'symbol_name': 'run',
                'new_content': 'def run(self):\n    return 3\n',
                'security_risk': 'LOW',
            }
        )


def test_edit_symbols_public_action_requires_new_content(monkeypatch, tmp_path):
    _use_tmp_workspace(monkeypatch, tmp_path)
    (tmp_path / 'mod.py').write_text('def a():\n    return 1\n', encoding='utf-8')

    action = _handle_edit_symbols_tool(
        {
            'path': 'mod.py',
            'edits': [{'symbol_name': 'a', 'new_content': '    return 2'}],
            'security_risk': 'LOW',
        }
    )
    assert isinstance(action, FileEditAction)
    assert action.command == 'edit_symbols'
    assert action.structured_payload == {
        'edits': [{'symbol_name': 'a', 'new_body': '    return 2'}]
    }

    with pytest.raises(FunctionCallValidationError, match='new_content'):
        _handle_edit_symbols_tool(
            {
                'path': 'mod.py',
                'edits': [{'symbol_name': 'a', 'new_body': '    return 2'}],
                'security_risk': 'LOW',
            }
        )


def test_multiedit_public_action_normalizes_operations_and_guards_content(
    monkeypatch, tmp_path
):
    _use_tmp_workspace(monkeypatch, tmp_path)

    action = _handle_multiedit_tool(
        {
            'operations': [
                {'command': 'create_file', 'path': 'a.py', 'content': 'A = 1\n'},
                {
                    'command': 'replace_string',
                    'path': 'README.md',
                    'old_string': 'old',
                    'new_string': 'new',
                },
            ],
            'security_risk': 'LOW',
        }
    )
    assert isinstance(action, FileEditAction)
    assert action.command == 'multi_edit'
    assert action.structured_payload == {
        'file_edits': [
            {'path': 'a.py', 'command': 'create_file', 'content': 'A = 1\n'},
            {
                'path': 'README.md',
                'command': 'replace_string',
                'old_string': 'old',
                'new_string': 'new',
                'replace_all': False,
            },
        ]
    }

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
