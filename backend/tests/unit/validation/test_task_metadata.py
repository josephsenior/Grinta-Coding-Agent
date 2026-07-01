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
