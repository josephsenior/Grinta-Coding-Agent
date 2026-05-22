import hashlib

from backend.execution.utils.file_editor import FileEditor, ToolResult


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


def test_expected_file_hash_guard_rejects_stale_content(tmp_path):
    target = tmp_path / 'x.py'
    target.write_bytes(b'alpha\n')
    editor = FileEditor(workspace_root=str(tmp_path))
    wrong_hash = hashlib.sha256(b'not-the-file').hexdigest()
    result = editor(
        command='edit',
        path='x.py',
        edit_mode='range',
        start_line=1,
        end_line=1,
        new_str='beta\n',
        expected_file_hash=wrong_hash,
    )
    assert result.error is not None
    assert 'hash guard' in (result.error or '').lower()
    assert target.read_text(encoding='utf-8') == 'alpha\n'


def test_expected_file_hash_guard_accepts_matching_content(tmp_path):
    target = tmp_path / 'x.py'
    body = 'alpha\n'
    target.write_bytes(body.encode('utf-8'))
    editor = FileEditor(workspace_root=str(tmp_path))
    digest = hashlib.sha256(body.encode('utf-8')).hexdigest()
    result = editor(
        command='edit',
        path='x.py',
        edit_mode='range',
        start_line=1,
        end_line=1,
        new_str='beta\n',
        expected_file_hash=digest,
    )
    assert result.error is None
    assert target.read_text(encoding='utf-8') == 'beta\n'


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


def test_write_verification_failure_returns_structured_error(tmp_path, monkeypatch):
    target = tmp_path / 'broken.py'
    target.write_text('x = 1\n', encoding='utf-8')
    editor = FileEditor(workspace_root=str(tmp_path))

    monkeypatch.setattr(
        editor,
        '_verify_post_write',
        lambda **_: ToolResult(
            output='',
            error='EDIT_VERIFICATION_FAILED: simulated',
            error_code='EDIT_VERIFICATION_FAILED',
            retryable=True,
            operation='edit',
            metadata={'verification_passed': False},
        ),
    )
    result = editor(
        command='edit',
        path='broken.py',
        edit_mode='range',
        start_line=1,
        end_line=1,
        new_str='x = 2\n',
    )
    assert result.error_code == 'EDIT_VERIFICATION_FAILED'
    assert result.retryable is True
