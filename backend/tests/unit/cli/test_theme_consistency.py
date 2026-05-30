from __future__ import annotations

from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

from backend.cli.repl import Repl
from backend.cli.status_chrome import StatusFields, pt_stats_row2_fragments
from backend.cli.theme import mark_err, mark_info, mark_ok, mark_prompt
from backend.cli.transcript import format_activity_result_secondary
from backend.core.config import AppConfig


def _make_repl() -> Repl:
    return Repl(cast(AppConfig, MagicMock()), MagicMock())


def test_transcript_uses_canonical_markers() -> None:
    ok = format_activity_result_secondary('done', kind='ok')
    err = format_activity_result_secondary('failed', kind='err')
    neutral = format_activity_result_secondary('note', kind='neutral')

    assert mark_ok() in ok.plain
    assert mark_err() in err.plain
    assert mark_info() in neutral.plain


def test_mark_ok_uses_ascii_when_flagged(monkeypatch) -> None:
    from backend.cli import theme as theme_mod

    monkeypatch.setattr(theme_mod, 'use_ascii_cli_symbols', lambda: True)
    assert theme_mod.mark_ok() == '+'


def test_prompt_marker_uses_theme_constant() -> None:
    repl = _make_repl()
    assert mark_prompt() in repl._prompt_message()


def test_prompt_stats_row2_omits_mcp_and_skills_by_default() -> None:
    fields = StatusFields(
        provider='openai',
        model='gpt-4o-mini',
        model_display='openai/gpt-4o-mini',
        token_display_compact='123/128k',
        cost_usd=0.1234,
        llm_calls=4,
        mcp_short='2',
        skills_short='5',
        ledger_status='Healthy',
        agent_state_label='Ready',
        autonomy_level='balanced',
        workspace_path='',
    )

    fragments = pt_stats_row2_fragments(
        fields,
        width=160,
        ledger_style='class:prompt.health.good',
    )
    rendered = ''.join(text for _, text in fragments)

    assert 'provider:' in rendered
    assert 'model:' in rendered
    assert '123/128k' in rendered
    assert '$0.123' in rendered
    assert 'Healthy' in rendered
    assert '4 calls' in rendered
    assert 'MCP:' not in rendered
    assert 'Skills:' not in rendered


def test_core_cli_renderers_avoid_raw_style_literals() -> None:
    repo = Path(__file__).resolve().parents[4]
    targets = (
        repo / 'backend/cli/transcript.py',
        repo / 'backend/cli/event_renderer.py',
        repo / 'backend/cli/confirmation.py',
        repo / 'backend/cli/_event_renderer/panels.py',
        repo / 'backend/cli/_event_renderer/action_renderers_mixin.py',
        repo / 'backend/cli/session_manager.py',
        repo / 'backend/cli/diff_renderer.py',
        repo / 'backend/cli/storage_cleanup.py',
        repo / 'backend/cli/_repl/run_helpers_mixin.py',
    )
    banned = ("style='dim'", "style='default'", "style='bold'", "style='bold dim'")
    for path in targets:
        content = path.read_text(encoding='utf-8')
        for needle in banned:
            assert needle not in content, f'{path} still contains {needle}'
