"""Tests for structured task metadata embedded in user messages."""

from __future__ import annotations

from backend.validation.task_metadata import (
    APP_TASK_JSON_PREFIX,
    extract_task_rubric,
    merge_task_fields,
    parse_task_from_user_message,
)


def test_parse_plain_message_unchanged() -> None:
    body, meta = parse_task_from_user_message('Just fix the bug in login')
    assert body == 'Just fix the bug in login'
    assert meta == {}


def test_parse_json_prefix_expected_files() -> None:
    raw = (
        f'{APP_TASK_JSON_PREFIX}{{"expected_output_files":["a.txt","b.py"]}}\n'
        'Implement the feature.'
    )
    body, meta = parse_task_from_user_message(raw)
    assert body == 'Implement the feature.'
    assert meta['expected_output_files'] == ['a.txt', 'b.py']


def test_parse_json_prefix_acceptance_criteria() -> None:
    raw = (
        f'{APP_TASK_JSON_PREFIX}{{"acceptance_criteria":["All tests pass"]}}\n'
        'Build the compiler.'
    )
    body, meta = parse_task_from_user_message(raw)
    assert body == 'Build the compiler.'
    _, _, acceptance, _ = merge_task_fields(body, meta)
    assert acceptance == ['All tests pass']


def test_invalid_json_falls_back_to_full_string() -> None:
    raw = f'{APP_TASK_JSON_PREFIX}not-json\nRest'
    body, meta = parse_task_from_user_message(raw)
    assert meta == {}
    assert body == raw


def test_empty_json_line_uses_rest_as_description() -> None:
    raw = f'{APP_TASK_JSON_PREFIX}\nOnly description'
    body, meta = parse_task_from_user_message(raw)
    assert body == 'Only description'
    assert meta == {}


def test_extract_validation_rubric_from_banner_section() -> None:
    description = """
============================================================
VALIDATION
============================================================

Before finishing:

1. Run make runtime
2. Run pytest tests/

Do not claim full success unless:
- All 10 tests pass
- Bootstrap diff is empty
"""
    _, acceptance = extract_task_rubric(description)
    assert 'Run make runtime' in acceptance
    assert 'Run pytest tests/' in acceptance
    assert 'All 10 tests pass' in acceptance
    assert 'Bootstrap diff is empty' in acceptance


def test_merge_task_fields_prefers_json_acceptance_over_prose() -> None:
    description = """
============================================================
VALIDATION
============================================================

1. Run pytest
"""
    _, meta = parse_task_from_user_message(
        f'{APP_TASK_JSON_PREFIX}{{"acceptance_criteria":["Explicit gate"]}}\n{description}'
    )
    _, _, acceptance, _ = merge_task_fields(description, meta)
    assert acceptance == ['Explicit gate']


def test_parse_task_empty_message() -> None:
    body, meta = parse_task_from_user_message("")
    assert body == ""
    assert meta == {}


def test_parse_task_single_line_no_newline() -> None:
    raw = f'{APP_TASK_JSON_PREFIX}{{"expected_output_files":["a.txt"]}}'
    body, meta = parse_task_from_user_message(raw)
    # No newline, falls back to full content for description, but JSON is successfully parsed!
    assert body == raw
    assert meta == {"expected_output_files": ["a.txt"]}

    # Empty JSON string on prefix line
    raw_empty = f'{APP_TASK_JSON_PREFIX}   \nRest'
    body2, meta2 = parse_task_from_user_message(raw_empty)
    assert body2 == "Rest"
    assert meta2 == {}


def test_parse_task_invalid_metadata_types() -> None:
    # Not a dictionary (string)
    raw_str = f'{APP_TASK_JSON_PREFIX}"not-a-dict"\nRest'
    body1, meta1 = parse_task_from_user_message(raw_str)
    assert body1 == raw_str
    assert meta1 == {}

    # Not a dictionary (list)
    raw_list = f'{APP_TASK_JSON_PREFIX}[1, 2, 3]\nRest'
    body2, meta2 = parse_task_from_user_message(raw_list)
    assert body2 == raw_list
    assert meta2 == {}


def test_extract_task_rubric_deduplication() -> None:
    description = """
============================================================
VALIDATION
============================================================
1. Run pytest
2. run pytest
"""
    # case-insensitive duplicates should be removed
    _, acceptance = extract_task_rubric(description)
    assert len(acceptance) == 1
    assert acceptance[0] == "Run pytest"


def test_extract_bullets_after_marker_formatting() -> None:
    description = """
============================================================
VALIDATION
============================================================
Do not claim full success unless:
- First item
- Second item
Plain text breaking the list
- Third item (should not be collected)
"""
    _, acceptance = extract_task_rubric(description)
    assert "First item" in acceptance
    assert "Second item" in acceptance
    assert "Third item" not in acceptance

    # Bullet markers not found
    desc_no_marker = """
============================================================
VALIDATION
============================================================
No bullet points here.
"""
    _, acceptance2 = extract_task_rubric(desc_no_marker)
    assert len(acceptance2) == 0


def test_extract_bullets_after_marker_numbered_list() -> None:
    description = """
============================================================
VALIDATION
============================================================
Final report must include:
1. Chart A
2. Chart B
"""
    _, acceptance = extract_task_rubric(description)
    assert "Chart A" in acceptance
    assert "Chart B" in acceptance


def test_merge_task_fields_comprehensive() -> None:
    # Test string list extraction and metadata merging
    meta = {
        "requirements": [123, "   valid requirement   ", ""],  # empty string should be ignored
        "acceptance_criteria": "not-a-list",
        "expected_output_files": ["out.txt", 456]  # invalid types mixed in
    }
    
    desc = "Regular description"
    desc_res, reqs, acc, files = merge_task_fields(desc, meta)
    
    assert desc_res == desc
    assert reqs == ["123", "valid requirement"]  # Coerced and stripped
    assert acc == []  # Not a list, defaults to rubric (empty)
    assert files is None  # Mixed non-string type (456) causes it to be discarded
