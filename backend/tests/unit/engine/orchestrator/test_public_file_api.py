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
    _handle_replace_string_tool,
)
from backend.engine.tools._file_edits import execute_find_symbols
from backend.ledger.action import (
    FileEditAction,
    FileReadAction,
    FindSymbolsAction,
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
    content = getattr(event, 'content', '')
    if content:
        return json.loads(str(content))
    tool_result = getattr(event, 'tool_result', None)
    if isinstance(tool_result, dict):
        return dict(tool_result)
    return {}


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
    assert action.overwrite is False

    existing_action = _handle_create_file_tool(
        {
            'path': 'existing.py',
            'content': 'print("new")\n',
            'security_risk': 'LOW',
        }
    )
    assert isinstance(existing_action, FileEditAction)
    assert existing_action.command == 'create_file'
    assert existing_action.overwrite is False

    overwrite_action = _handle_create_file_tool(
        {
            'path': 'existing.py',
            'content': 'print("new")\n',
            'overwrite': True,
            'security_risk': 'LOW',
        }
    )
    assert overwrite_action.overwrite is True

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
