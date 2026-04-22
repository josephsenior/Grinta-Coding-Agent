import hashlib

from backend.execution.utils.file_editor import FileEditor, ToolResult, normalize_quotes


def test_ws_tolerant_replace_failure_message_improved():
    fe = FileEditor()
    # Content with two simple functions
    content = 'def a():\n    return 1\n\ndef b():\n    return 2\n'

    # old_str not present; multi-line pattern
    old_str = 'def c():\n    return 3\n'

    res = fe._apply_str_replace(content, old_str, 'REPLACED')
    assert isinstance(res, ToolResult)
    assert res.error is not None and res.error.strip() != ''
    # Ensure we don't return the vague legacy internal-failure message
    assert 'Whitespace-based matching failed internally.' not in (res.error or '')


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


def test_edit_mode_section_markdown_replace(tmp_path):
    target = tmp_path / 'README.md'
    target.write_text('## Intro\nold\n\n## Next\nkeep\n', encoding='utf-8')
    editor = FileEditor(workspace_root=str(tmp_path))
    result = editor(
        command='edit',
        path='README.md',
        edit_mode='section',
        anchor_type='markdown_heading',
        anchor_value='Intro',
        section_action='replace',
        section_content='## Intro\nnew\n\n',
    )
    assert result.error is None
    assert '## Intro\nnew\n\n## Next\nkeep\n' == target.read_text(encoding='utf-8')


def test_edit_mode_patch_applies_single_hunk(tmp_path):
    target = tmp_path / 'sample.txt'
    target.write_bytes(b'a\nb\nc\n')
    editor = FileEditor(workspace_root=str(tmp_path))
    patch = '@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n'
    result = editor(
        command='edit', path='sample.txt', edit_mode='patch', patch_text=patch
    )
    assert result.error is None
    assert target.read_text(encoding='utf-8') == 'a\nB\nc\n'


def test_edit_mode_format_json_set(tmp_path):
    target = tmp_path / 'config.json'
    target.write_text('{"name":"app","scripts":{"test":"vitest"}}', encoding='utf-8')
    editor = FileEditor(workspace_root=str(tmp_path))
    result = editor(
        command='edit',
        path='config.json',
        edit_mode='format',
        format_kind='json',
        format_op='set',
        format_path='$.scripts.build',
        format_value='vite build',
    )
    assert result.error is None
    assert '"build": "vite build"' in target.read_text(encoding='utf-8')


def test_expected_file_hash_guard_rejects_stale_content(tmp_path):
    target = tmp_path / 'x.py'
    target.write_bytes(b'alpha\n')
    editor = FileEditor(workspace_root=str(tmp_path))
    wrong_hash = hashlib.sha256(b'not-the-file').hexdigest()
    result = editor(
        command='edit',
        path='x.py',
        old_str='alpha',
        new_str='beta',
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
        old_str='alpha',
        new_str='beta',
        expected_file_hash=digest,
    )
    assert result.error is None
    assert target.read_text(encoding='utf-8') == 'beta\n'


def test_normalize_quotes_matches_claude_index_slice(tmp_path):
    """Curly quotes in file + straight in needle resolve via normalizeQuotes + slice."""
    target = tmp_path / 't.txt'
    target.write_bytes('x = \u201cok\u201d\n'.encode('utf-8'))
    editor = FileEditor(workspace_root=str(tmp_path))
    actual = editor._find_actual_substring_for_replace(
        target.read_text(encoding='utf-8'), 'x = "ok"'
    )
    assert actual == 'x = \u201cok\u201d'
    assert normalize_quotes(actual) == normalize_quotes('x = "ok"')


def test_straight_quotes_match_curly_quotes_in_file(tmp_path):
    target = tmp_path / 'q.txt'
    # Typographic double quotes in source (non-code file avoids Python syntax validation)
    target.write_bytes('msg = \u201chello\u201d\n'.encode('utf-8'))
    editor = FileEditor(workspace_root=str(tmp_path))
    result = editor(
        command='edit',
        path='q.txt',
        old_str='msg = "hello"',
        new_str='msg = "bye"',
    )
    assert result.error is None
    out = target.read_text(encoding='utf-8')
    assert '\u201c' in out or '\u201d' in out
    assert 'bye' in out


def test_crlf_preserved_on_write(tmp_path):
    target = tmp_path / 'lines.txt'
    target.write_bytes(b'one\r\ntwo\r\n')
    editor = FileEditor(workspace_root=str(tmp_path))
    result = editor(
        command='edit',
        path='lines.txt',
        old_str='one',
        new_str='ONE',
    )
    assert result.error is None
    raw = target.read_bytes()
    assert b'\r\n' in raw
    assert raw.startswith(b'ONE')
