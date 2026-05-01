"""Regression tests for unified HUD / toolbar / Live footer chrome."""

from __future__ import annotations

import pytest

from backend.cli.hud import HUDBar
from backend.cli.status_chrome import (
    STATUS_CHROME_COMPACT_WIDTH,
    pt_compact_line_plain,
    pt_stats_row2_fragments,
    rich_compact_hud_line,
    rich_fake_prompt_group,
    status_fields_from_hud,
)
from backend.cli.theme import prompt_toolkit_style_dict


def test_status_fields_token_display_matches_hud_style() -> None:
    bar = HUDBar()
    bar.state.context_tokens = 1500
    bar.state.context_limit = 8000
    bar.state.token_usage_estimated = True
    fields = status_fields_from_hud(bar.state, bar.bundled_skill_count)
    assert fields.token_display_compact == '1.5K/8.0K~'


def test_pt_compact_line_joins_same_segments_as_toolbar_contract() -> None:
    bar = HUDBar()
    bar.state.workspace_path = '/tmp/proj/sub'
    bar.state.agent_state_label = 'Running'
    bar.state.autonomy_level = 'full'
    bar.state.model = 'openai/google/gemini'
    bar.state.context_tokens = 100
    bar.state.context_limit = 128_000
    bar.state.cost_usd = 0.012
    bar.state.ledger_status = 'Healthy'
    fields = status_fields_from_hud(bar.state, bar.bundled_skill_count)
    line = pt_compact_line_plain(fields)
    assert 'Running' in line
    assert 'autonomy:full' in line
    assert 'google/gemini' in line
    assert '$0.012' in line


def test_rich_hud_line_plain_snapshot() -> None:
    bar = HUDBar()
    bar.state.model = 'google/gemini-flash'
    bar.state.context_tokens = 0
    bar.state.context_limit = 0
    bar.state.cost_usd = 0.0
    bar.state.llm_calls = 3
    bar.state.mcp_servers = 2
    fields = status_fields_from_hud(bar.state, 24)
    text = rich_compact_hud_line(fields)
    plain = text.plain.strip()
    assert 'Balanced' in plain
    assert 'google/gemini-flash' in plain
    assert 'MCP: 2' in plain
    assert 'Skills:' in plain


def test_fake_prompt_is_single_block_when_narrow() -> None:
    bar = HUDBar()
    fields = status_fields_from_hud(bar.state, bar.bundled_skill_count)
    group = rich_fake_prompt_group(fields, STATUS_CHROME_COMPACT_WIDTH - 1)
    assert len(group.renderables) == 1


def test_fake_prompt_full_has_input_rule_and_metrics_when_wide() -> None:
    bar = HUDBar()
    fields = status_fields_from_hud(bar.state, bar.bundled_skill_count)
    group = rich_fake_prompt_group(fields, 100)
    assert len(group.renderables) == 4


def test_pt_stats_row2_includes_tokens_cost_and_ledger() -> None:
    bar = HUDBar()
    bar.state.ledger_status = 'Review'
    fields = status_fields_from_hud(bar.state, bar.bundled_skill_count)
    frags = pt_stats_row2_fragments(
        fields,
        width=200,
        ledger_style='class:prompt.health.warn',
    )
    blob = ''.join(t for _, t in frags)
    assert 'Tokens:' in blob
    assert 'Cost:' in blob
    assert 'Review' in blob


def test_prompt_toolkit_no_color_styles_have_no_hex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When NO_COLOR is active, PT style strings must stay ANSI-oriented."""
    monkeypatch.setenv('NO_COLOR', '1')
    spec = prompt_toolkit_style_dict()
    for key, val in spec.items():
        assert '#' not in val, f'{key}={val!r}'


def test_prompt_toolkit_color_styles_include_brand_and_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('NO_COLOR', raising=False)
    monkeypatch.delenv('GRINTA_NO_COLOR', raising=False)
    spec = prompt_toolkit_style_dict()
    assert 'prompt.brand' in spec
    assert 'completion-menu' in spec
