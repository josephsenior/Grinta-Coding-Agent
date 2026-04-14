"""Tests for canonical FileEditor command handling."""

from __future__ import annotations

from pathlib import Path

from backend.execution.utils.file_editor import FileEditor


def test_file_editor_replace_text_command(tmp_path: Path) -> None:
    editor = FileEditor(workspace_root=str(tmp_path))
    p = tmp_path / 'sample.txt'
    p.write_text('hello old world\n', encoding='utf-8')

    result = editor(
        command='replace_text',
        path='sample.txt',
        old_str='old',
        new_str='new',
    )

    assert result.error is None
    assert 'updated' in result.output.lower()
    assert p.read_text(encoding='utf-8') == 'hello new world\n'


def test_file_editor_insert_text_command(tmp_path: Path) -> None:
    editor = FileEditor(workspace_root=str(tmp_path))
    p = tmp_path / 'sample.txt'
    p.write_text('a\nb\n', encoding='utf-8')

    result = editor(
        command='insert_text',
        path='sample.txt',
        new_str='x',
        insert_line=2,
    )

    assert result.error is None
    assert 'updated' in result.output.lower()
    assert p.read_text(encoding='utf-8') == 'a\nx\nb\n'


def test_file_editor_undo_last_edit_empty_history(tmp_path: Path) -> None:
    editor = FileEditor(workspace_root=str(tmp_path))
    p = tmp_path / 'sample.txt'
    p.write_text('hello\n', encoding='utf-8')

    result = editor(command='undo_last_edit', path='sample.txt')

    assert result.error is not None
    assert 'no undo history' in result.error.lower()


def test_file_editor_undo_after_replace_text(tmp_path: Path) -> None:
    editor = FileEditor(workspace_root=str(tmp_path))
    p = tmp_path / 'sample.txt'
    p.write_text('hello old world\n', encoding='utf-8')

    assert (
        editor(
            command='replace_text',
            path='sample.txt',
            old_str='old',
            new_str='new',
        ).error
        is None
    )
    assert p.read_text(encoding='utf-8') == 'hello new world\n'

    undo = editor(command='undo_last_edit', path='sample.txt')
    assert undo.error is None
    assert p.read_text(encoding='utf-8') == 'hello old world\n'


def test_file_editor_undo_after_create_file_removes_file(tmp_path: Path) -> None:
    editor = FileEditor(workspace_root=str(tmp_path))
    p = tmp_path / 'new.txt'
    assert not p.exists()

    assert (
        editor(
            command='create_file',
            path='new.txt',
            file_text='only',
        ).error
        is None
    )
    assert p.read_text(encoding='utf-8') == 'only'

    undo = editor(command='undo_last_edit', path='new.txt')
    assert undo.error is None
    assert not p.exists()
