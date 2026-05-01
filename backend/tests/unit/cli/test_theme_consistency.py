from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock
from pathlib import Path

from backend.cli.hud import HUDBar
from backend.cli.repl import Repl
from backend.cli.theme import MARK_ERR, MARK_INFO, MARK_OK, MARK_PROMPT
from backend.cli.transcript import format_activity_result_secondary
from backend.core.config import AppConfig


def _make_repl() -> Repl:
    return Repl(cast(AppConfig, MagicMock()), MagicMock())


def test_transcript_uses_canonical_markers() -> None:
    ok = format_activity_result_secondary('done', kind='ok')
    err = format_activity_result_secondary('failed', kind='err')
    neutral = format_activity_result_secondary('note', kind='neutral')

    assert MARK_OK in ok.plain
    assert MARK_ERR in err.plain
    assert MARK_INFO in neutral.plain


def test_prompt_marker_uses_theme_constant() -> None:
    repl = _make_repl()
    assert MARK_PROMPT in repl._prompt_message()


def test_prompt_stats_row2_omits_mcp_and_skills_by_default() -> None:
    repl = _make_repl()
    repl._hud = HUDBar()
    data = {
        'workspace': '',
        'provider': 'openai',
        'model': 'gpt-4o-mini',
        'token_display': '123/128k',
        'cost': '$0.1234',
        'calls': '4 calls',
        'mcp': '2 mcp',
        'skills': '5 skills',
        'ledger': 'Healthy',
    }

    fragments = repl._prompt_stats_row2_fragments(data, width=160)
    rendered = ''.join(text for _, text in fragments)

    assert 'provider:' in rendered
    assert 'model:' in rendered
    assert '123/128k' in rendered
    assert '$0.1234' in rendered
    assert 'Healthy' in rendered
    assert '4 calls' in rendered
    assert '2 mcp' not in rendered
    assert '5 skills' not in rendered


def test_core_cli_renderers_avoid_raw_style_literals() -> None:
    repo = Path(__file__).resolve().parents[4]
    targets = (
        repo / 'backend/cli/transcript.py',
        repo / 'backend/cli/event_renderer.py',
        repo / 'backend/cli/confirmation.py',
        repo / 'backend/cli/_event_renderer/panels.py',
        repo / 'backend/cli/_event_renderer/action_renderers_mixin.py',
        repo / 'backend/cli/session_manager.py',
        repo / 'backend/cli/sessions_cli.py',
        repo / 'backend/cli/diff_renderer.py',
        repo / 'backend/cli/main.py',
    )
    banned = ("style='dim'", "style='default'", "style='bold'", "style='bold dim'")
    for path in targets:
        content = path.read_text(encoding='utf-8')
        for needle in banned:
            assert needle not in content, f'{path} still contains {needle}'
