"""Unit tests for error category rule tables."""

from __future__ import annotations

from backend.cli.event_rendering.error_categories import (
    ALL_GUIDANCE_RULES,
    NOTICE_TITLE_RULES,
    get_all_guidance_rules,
    get_notice_title_rules,
)
from backend.cli.event_rendering.error_panel import error_guidance, notice_panel_title


def test_guidance_rule_tables_are_non_empty() -> None:
    assert get_all_guidance_rules() == ALL_GUIDANCE_RULES
    assert get_notice_title_rules() == NOTICE_TITLE_RULES
    assert len(ALL_GUIDANCE_RULES) > 10
    assert len(NOTICE_TITLE_RULES) > 5


def test_error_guidance_matches_auth_failure() -> None:
    guidance = error_guidance('Error: 401 unauthorized invalid api key')
    assert guidance is not None
    assert guidance.steps


def test_error_guidance_matches_range_edit_missing_lines() -> None:
    guidance = error_guidance(
        'edit requires start_line and end_line (missing: end_line).'
    )
    assert guidance is not None
    assert guidance.error_code == 'ERR-TE-001'


def test_error_guidance_matches_stuck_loop() -> None:
    guidance = error_guidance('STUCK_LOOP: repeating actions without progress.')
    assert guidance is not None
    assert guidance.error_code == 'ERR-SYS-013'


def test_notice_panel_title_uses_rule_table() -> None:
    assert notice_panel_title('rate limit exceeded') == 'Rate or quota limit'
    assert notice_panel_title('connection reset by peer') == 'Connection issue'
    assert (
        notice_panel_title('request timed out waiting for model') == 'Request timed out'
    )
