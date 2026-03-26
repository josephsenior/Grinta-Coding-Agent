"""Tests for structured task metadata embedded in user messages."""

from __future__ import annotations

from backend.validation.task_metadata import (
    FORGE_TASK_JSON_PREFIX,
    parse_task_from_user_message,
)


def test_parse_plain_message_unchanged() -> None:
    body, meta = parse_task_from_user_message("Just fix the bug in login")
    assert body == "Just fix the bug in login"
    assert meta == {}


def test_parse_json_prefix_expected_files() -> None:
    raw = (
        f'{FORGE_TASK_JSON_PREFIX}{{"expected_output_files":["a.txt","b.py"]}}\n'
        "Implement the feature."
    )
    body, meta = parse_task_from_user_message(raw)
    assert body == "Implement the feature."
    assert meta["expected_output_files"] == ["a.txt", "b.py"]


def test_invalid_json_falls_back_to_full_string() -> None:
    raw = f"{FORGE_TASK_JSON_PREFIX}not-json\nRest"
    body, meta = parse_task_from_user_message(raw)
    assert meta == {}
    assert body == raw


def test_empty_json_line_uses_rest_as_description() -> None:
    raw = f"{FORGE_TASK_JSON_PREFIX}\nOnly description"
    body, meta = parse_task_from_user_message(raw)
    assert body == "Only description"
    assert meta == {}
