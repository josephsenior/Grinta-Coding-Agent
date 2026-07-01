"""Unit tests for error panel helper functions."""

from __future__ import annotations

from rich.panel import Panel
from rich.text import Text

from backend.cli.event_rendering.error_panel import (
    build_error_panel,
    build_llm_stream_fallback_panel,
    build_recovery_text,
    build_retry_panel,
    error_guidance,
    notice_panel_title,
    split_error_text,
    use_recoverable_notice_style,
)
from backend.cli.event_rendering.panels import ErrorGuidance
from backend.ledger.observation.error import (
    ERROR_CATEGORY_AUTH,
    ERROR_CATEGORY_NETWORK,
    ERROR_CATEGORY_RATE_LIMIT,
    ERROR_CATEGORY_TIMEOUT,
)


def test_use_recoverable_notice_style_by_category() -> None:
    assert use_recoverable_notice_style('x', error_category=ERROR_CATEGORY_TIMEOUT)
    assert use_recoverable_notice_style('x', error_category=ERROR_CATEGORY_NETWORK)
    assert not use_recoverable_notice_style('x', error_category=ERROR_CATEGORY_AUTH)


def test_use_recoverable_notice_style_text_fallback() -> None:
    assert use_recoverable_notice_style('connection reset by peer')
    assert not use_recoverable_notice_style('invalid api key provided')


def test_split_error_text_strips_validation_and_summarizes() -> None:
    raw = 'ERROR:\nProvider failed\nline two\n<APP_RESULT_VALIDATION>hidden</APP_RESULT_VALIDATION>'
    summary, detail = split_error_text(raw)
    assert summary == 'Provider failed'
    assert detail == 'line two'
    assert split_error_text('   ') == ('Unknown error', '')


def test_notice_panel_title_prefers_category() -> None:
    assert notice_panel_title('x', error_category=ERROR_CATEGORY_RATE_LIMIT) == (
        'Rate or quota limit'
    )
    assert notice_panel_title('request timed out') == 'Request timed out'
    assert notice_panel_title('misc') == 'Heads-up'


def test_error_guidance_matches_known_patterns() -> None:
    guidance = error_guidance('Error: 401 unauthorized invalid api key')
    assert guidance is not None
    assert guidance.steps


def test_build_llm_stream_fallback_panel_shape() -> None:
    panel = build_llm_stream_fallback_panel()
    assert isinstance(panel, Panel)


def test_build_retry_panel_includes_eta() -> None:
    panel = build_retry_panel(2, 5, kind='llm', eta=0.5)
    assert isinstance(panel, Panel)


def test_build_error_panel_rate_limit_is_compact() -> None:
    panel = build_error_panel(
        'rate limit exceeded',
        error_category=ERROR_CATEGORY_RATE_LIMIT,
    )
    assert isinstance(panel, Text)


def test_build_error_panel_regular_error_is_panel() -> None:
    panel = build_error_panel(
        'ERROR:\nSomething broke badly\nmore detail',
        error_category=ERROR_CATEGORY_AUTH,
        content_width=100,
    )
    assert isinstance(panel, Panel)


def test_build_error_tui_renderable_is_group() -> None:
    from rich.console import Group

    from backend.cli.event_rendering.error_panel import build_error_tui_renderable

    renderable = build_error_tui_renderable(
        'ERROR:\nSomething broke badly\nmore detail',
        error_category=ERROR_CATEGORY_AUTH,
        content_width=100,
    )
    assert isinstance(renderable, Group)


def test_build_recovery_text_includes_steps() -> None:
    guidance = ErrorGuidance(
        summary='Check your API key.',
        steps=('Open settings', 'Paste a valid key'),
        error_code='AUTH_401',
    )
    recovery = build_recovery_text(guidance, wrap_width=80)
    assert isinstance(recovery, Text)
    assert 'Open settings' in recovery.plain


def test_build_recovery_text_notice_style() -> None:
    guidance = ErrorGuidance(
        summary='',
        steps=('Wait a moment', 'Retry the request'),
        omit_summary_in_recovery=True,
    )
    recovery = build_recovery_text(guidance, for_notice=True)
    assert 'Next steps' in recovery.plain
