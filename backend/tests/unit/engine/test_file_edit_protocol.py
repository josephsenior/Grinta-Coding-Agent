from __future__ import annotations

from pathlib import Path

from backend.engine.file_edit_protocol import (
    EditTransaction,
    EditTransactionStore,
    apply_edit_from_transaction,
    build_editor_mode_prompt,
    parse_editor_response,
)


def _txn() -> EditTransaction:
    return EditTransaction(
        transaction_id='edit_abc123',
        session_id='s1',
        path='pkg/app.py',
        operation='replace_range',
        delimiter='GRINTA_END_1234567890abcdef12345678',
        metadata={'start_line': 1, 'end_line': 2},
        status='pending_content',
    )


def _block(content: str, txn: EditTransaction | None = None) -> str:
    txn = txn or _txn()
    return (
        '<file_edit>\n'
        f'{content}'
        f'{txn.delimiter}\n'
        '</file_edit>\n'
    )


def test_parse_valid_file_edit_block():
    txn = _txn()
    parsed = parse_editor_response(_block("print('ok')\n", txn), txn)
    assert parsed.ok
    assert parsed.content == "print('ok')\n"


def test_parse_preserves_indentation():
    txn = _txn()
    parsed = parse_editor_response(_block('    def f():\n        return 1\n', txn), txn)
    assert parsed.content == '    def f():\n        return 1\n'


def test_parse_preserves_trailing_newline_in_content():
    txn = _txn()
    parsed = parse_editor_response(_block('value = 1\n', txn), txn)
    assert parsed.content.endswith('\n')


def test_parse_preserves_leading_blank_lines_inside_content():
    txn = _txn()
    parsed = parse_editor_response(_block('\n\nvalue = 1\n', txn), txn)
    assert parsed.content == '\n\nvalue = 1\n'


def test_parse_rejects_missing_opening_tag():
    txn = _txn()
    parsed = parse_editor_response('value = 1\n', txn)
    assert not parsed.ok
    assert parsed.error_code == 'MISSING_OPEN_TAG'


def test_parse_accepts_optional_transaction_id():
    txn = _txn()
    text = f'<file_edit transaction_id="{txn.transaction_id}">\nx\n{txn.delimiter}\n</file_edit>\n'
    parsed = parse_editor_response(text, txn)
    assert parsed.ok
    assert parsed.content == 'x\n'


def test_parse_rejects_missing_delimiter():
    txn = _txn()
    text = '<file_edit>\nx\n</file_edit>\n'
    parsed = parse_editor_response(text, txn)
    assert not parsed.ok
    assert parsed.error_code == 'MISSING_DELIMITER'


def test_parse_rejects_missing_closing_tag():
    txn = _txn()
    text = f'<file_edit>\nx\n{txn.delimiter}\n'
    parsed = parse_editor_response(text, txn)
    assert not parsed.ok
    assert parsed.error_code == 'MISSING_CLOSE_TAG'


def test_parse_allows_markdown_fences_inside_raw_content():
    txn = _txn()
    content = '```python\nx\n```\n'
    parsed = parse_editor_response(_block(content, txn), txn)
    assert parsed.ok
    assert parsed.content == content


def test_parse_accepts_single_markdown_fence_wrapping_block():
    txn = _txn()
    text = '```xml\n' + _block('x\n', txn) + '```\n'
    parsed = parse_editor_response(text, txn)
    assert parsed.ok
    assert parsed.content == 'x\n'


def test_parse_rejects_markdown_fence_wrapper_with_extra_prose():
    txn = _txn()
    text = '```xml\nhere\n' + _block('x\n', txn) + '```\n'
    parsed = parse_editor_response(text, txn)
    assert not parsed.ok
    assert parsed.error_code == 'MARKDOWN_FENCE_DETECTED'


def test_parse_rejects_markdown_fence_after_block():
    txn = _txn()
    parsed = parse_editor_response(_block('x\n', txn) + '```\n', txn)
    assert not parsed.ok
    assert parsed.error_code == 'MARKDOWN_FENCE_DETECTED'


def test_parse_rejects_explanatory_prose_after_block():
    txn = _txn()
    parsed = parse_editor_response(_block('x\n', txn) + 'done\n', txn)
    assert not parsed.ok
    assert parsed.error_code == 'EXTRA_TEXT_OUTSIDE_BLOCK'


def test_parse_rejects_content_larger_than_limit():
    txn = _txn()
    parsed = parse_editor_response(_block('x' * 11 + '\n', txn), txn, max_content_size=10)
    assert not parsed.ok
    assert parsed.error_code == 'CONTENT_TOO_LARGE'


def test_parse_does_not_corrupt_xml_like_strings_inside_content():
    txn = _txn()
    content = 'text = "<file_edit transaction_id=\\"not_real\\">"\n'
    parsed = parse_editor_response(_block(content, txn), txn)
    assert parsed.ok
    assert parsed.content == content


def test_parse_preserves_first_content_character_after_opening_line():
    txn = _txn()
    parsed = parse_editor_response(_block('first_char_survives\n', txn), txn)
    assert parsed.content == 'first_char_survives\n'


def test_transaction_store_generates_unique_transaction_ids():
    store = EditTransactionStore()
    first = store.create_transaction('s1', 'a.py', 'create', {})
    second = store.create_transaction('s2', 'b.py', 'create', {})
    assert first.transaction_id != second.transaction_id
    assert first.transaction_id.startswith('edit_')
    assert second.transaction_id.startswith('edit_')


def test_transaction_store_generates_long_unique_delimiters():
    store = EditTransactionStore()
    first = store.create_transaction('s1', 'a.py', 'create', {})
    second = store.create_transaction('s2', 'b.py', 'create', {})
    assert first.delimiter != second.delimiter
    assert first.delimiter.startswith('GRINTA_END_')
    assert len(first.delimiter.removeprefix('GRINTA_END_')) >= 24


def test_transaction_store_is_session_scoped():
    store = EditTransactionStore()
    one = store.create_transaction('s1', 'a.py', 'create', {})
    two = store.create_transaction('s2', 'b.py', 'create', {})
    assert store.get_active_transaction('s1') is one
    assert store.get_active_transaction('s2') is two


def test_clearing_transaction_only_clears_that_session():
    store = EditTransactionStore()
    store.create_transaction('s1', 'a.py', 'create', {})
    two = store.create_transaction('s2', 'b.py', 'create', {})
    store.clear_active_transaction('s1')
    assert store.get_active_transaction('s1') is None
    assert store.get_active_transaction('s2') is two


def test_retry_count_can_increment_on_parse_failure():
    store = EditTransactionStore()
    txn = store.create_transaction('s1', 'a.py', 'create', {})
    parsed = parse_editor_response('bad', txn)
    assert not parsed.ok
    txn.retry_count += 1
    store.update_transaction('s1', txn)
    assert store.get_active_transaction('s1').retry_count == 1


def test_editor_mode_prompt_explicitly_requests_raw_plain_text() -> None:
    txn = _txn()
    prompt = build_editor_mode_prompt(txn, target_context='print("hello")\n')

    assert 'raw file content' in prompt
    assert 'Do not serialize it as JSON or a tool payload' in prompt
    assert '<current_target>' in prompt
    assert '<file_edit>' in prompt
    assert '<file_edit transaction_id=' not in prompt


def test_editor_mode_prompt_mentions_json_for_edit_symbols() -> None:
    txn = EditTransaction(
        transaction_id='edit_json1',
        session_id='s1',
        path='pkg/app.py',
        operation='edit_symbols',
        delimiter='GRINTA_END_json1',
        metadata={},
        status='pending_content',
    )
    prompt = build_editor_mode_prompt(txn)
    assert '"edits"' in prompt


def test_editor_mode_prompt_mentions_json_for_multi_edit() -> None:
    txn = EditTransaction(
        transaction_id='edit_json2',
        session_id='s1',
        path='<batch>',
        operation='multi_edit',
        delimiter='GRINTA_END_json2',
        metadata={},
        status='pending_content',
    )
    prompt = build_editor_mode_prompt(txn)
    assert '"file_edits"' in prompt


def test_prompt_assets_include_concise_file_edit_policy() -> None:
    root = Path(__file__).resolve().parents[3] / 'engine' / 'prompts'
    routing = (root / 'system_partial_00_routing.md').read_text(encoding='utf-8')
    tools = (root / 'system_partial_02_tools.md').read_text(encoding='utf-8')

    assert 'After `start_file_edit`, the runtime enters FILE EDITOR MODE.' in routing
    assert 'Do not output `<file_edit>` blocks, do not manually write XML' in routing
    assert 'File Editing Policy' in tools
    assert 'Never pass multiline file content through JSON tool arguments.' in tools
