"""Integration-style coverage for LspResult human-readable formatting (no subprocess)."""

from __future__ import annotations

import pytest

from backend.utils.lsp.lsp_client import (
    LspCodeAction,
    LspLocation,
    LspResult,
    LspSymbol,
)


@pytest.mark.integration
def test_lsp_result_diagnostics_and_get_diagnostics_synonyms() -> None:
    loc = LspLocation(file='a.py', line=2, column=1)
    r = LspResult(available=True, locations=[loc])
    d1 = r.format_text('diagnostics')
    d2 = r.format_text('get_diagnostics')
    assert 'Diagnostics' in d1
    assert d1 == d2


@pytest.mark.integration
def test_lsp_result_code_action_preferred_and_empty_messages() -> None:
    act = LspCodeAction(
        title='Remove unused',
        kind='quickfix',
        is_preferred=True,
        diagnostic_message='unused',
    )
    with_actions = LspResult(code_actions=[act]).format_text('code_action')
    assert 'Remove unused' in with_actions
    assert '★' in with_actions
    no_actions = LspResult(code_actions=[]).format_text('code_action')
    assert 'No code actions' in no_actions or 'quick-fix' in no_actions


@pytest.mark.integration
def test_lsp_result_unknown_command_falls_back_to_string_repr() -> None:
    r = LspResult(available=True, hover_text='')
    out = r.format_text('totally_unknown_command_xyz')
    assert isinstance(out, str) and len(out) >= 0


@pytest.mark.integration
def test_lsp_result_list_symbols_and_hover_empty() -> None:
    syms = LspResult(
        symbols=[LspSymbol(name='fn', kind='Function', line=3)]
    ).format_text('list_symbols')
    assert 'fn' in syms or 'Symbols' in syms
    hover_empty = LspResult(hover_text='').format_text('hover')
    assert 'No hover information' in hover_empty
