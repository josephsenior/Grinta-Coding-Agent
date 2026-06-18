from backend.execution.utils.file_editor import FileEditor


def test_edit_mode_range_with_hash_guard(tmp_path):
    target = tmp_path / 'doc.txt'
    target.write_bytes(b'one\ntwo\nthree\n')
    editor = FileEditor(workspace_root=str(tmp_path))
    slice_hash = editor._sha256_text('two\n')
    result = editor(
        command='edit',
        path='doc.txt',
        edit_mode='range',
        start_line=2,
        end_line=2,
        new_str='TWO\n',
        expected_hash=slice_hash,
    )
    assert result.error is None
    assert target.read_text(encoding='utf-8') == 'one\nTWO\nthree\n'


def test_edit_mode_range_replaces_entire_inclusive_span(tmp_path):
    target = tmp_path / 'doc.txt'
    target.write_text('one\ntwo\nthree\nfour\n', encoding='utf-8')
    editor = FileEditor(workspace_root=str(tmp_path))
    result = editor(
        command='edit',
        path='doc.txt',
        edit_mode='range',
        start_line=2,
        end_line=3,
        new_str='TWO\nTHREE\n',
    )
    assert result.error is None
    assert target.read_text(encoding='utf-8') == 'one\nTWO\nTHREE\nfour\n'


def test_crlf_preserved_on_write(tmp_path):
    target = tmp_path / 'lines.txt'
    target.write_bytes(b'one\r\ntwo\r\n')
    editor = FileEditor(workspace_root=str(tmp_path))
    result = editor(
        command='edit',
        path='lines.txt',
        edit_mode='range',
        start_line=1,
        end_line=1,
        new_str='ONE\r\n',
    )
    assert result.error is None
    raw = target.read_bytes()
    assert b'\r\n' in raw
    assert raw.startswith(b'ONE')


def test_edit_result_includes_verification_receipt(tmp_path):
    target = tmp_path / 'receipt.py'
    target.write_text('a = 1\nb = 2\n', encoding='utf-8')
    editor = FileEditor(workspace_root=str(tmp_path))
    result = editor(
        command='edit',
        path='receipt.py',
        edit_mode='range',
        start_line=2,
        end_line=2,
        new_str='b = 99\n',
    )
    assert result.error is None
    assert result.metadata is not None
    assert result.metadata['verification_passed'] is True
    assert result.metadata['target_kind'] == 'range'
    assert result.metadata['changed_line_spans'] == [{'start_line': 2, 'end_line': 2}]
