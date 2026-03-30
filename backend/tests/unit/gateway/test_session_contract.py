"""Tests for backend.gateway.session.session_contract."""

from __future__ import annotations

from unittest.mock import patch

from backend.gateway.session.session_contract import normalize_replay_cursor


def test_normalize_replay_cursor_uses_app_env_default_limit() -> None:
    with patch.dict("os.environ", {"APP_TRAJECTORY_DEFAULT_LIMIT": "250"}, clear=False):
        cursor = normalize_replay_cursor(since_id=None, limit=None)

    assert cursor.start_id == 0
    assert cursor.limit == 250


def test_normalize_replay_cursor_invalid_app_env_falls_back() -> None:
    with patch.dict("os.environ", {"APP_TRAJECTORY_DEFAULT_LIMIT": "bogus"}, clear=False):
        cursor = normalize_replay_cursor(since_id=None, limit=None, default_limit=123)

    assert cursor.limit == 123


def test_normalize_replay_cursor_since_id_is_inclusive_lower_bound() -> None:
    cursor = normalize_replay_cursor(since_id=7, limit=20)

    assert cursor.since_id == 7
    assert cursor.start_id == 8
    assert cursor.limit == 20