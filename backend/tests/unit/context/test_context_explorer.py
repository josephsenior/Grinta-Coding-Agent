"""Tests for deterministic context exploration."""

from __future__ import annotations

from backend.context import context_explorer


def test_explorer_ranks_mentioned_path_and_matching_symbol(tmp_path) -> None:
    source = tmp_path / 'backend' / 'auth.py'
    source.parent.mkdir()
    source.write_text(
        'def refresh_token():\n    return "ok"\n',
        encoding='utf-8',
    )
    other = tmp_path / 'backend' / 'billing.py'
    other.write_text('def charge_card():\n    return None\n', encoding='utf-8')

    result = context_explorer.explore_context(
        'fix backend/auth.py token refresh',
        tmp_path,
    )

    assert result.candidates
    top = result.candidates[0]
    assert top.path == 'backend/auth.py'
    assert 'mentioned in task' in top.reasons
    assert 'refresh_token' in top.symbols


def test_explorer_uses_content_hits_as_candidate_signal(tmp_path, monkeypatch) -> None:
    source = tmp_path / 'src' / 'session.ts'
    source.parent.mkdir()
    source.write_text('export function retryToken() {}\n', encoding='utf-8')

    def fake_content_hits(_root, _terms):
        return {'src/session.ts': {'retry', 'token'}}

    monkeypatch.setattr(context_explorer, '_content_hits', fake_content_hits)

    result = context_explorer.explore_context('update retry token handler', tmp_path)

    assert result.candidates
    top = result.candidates[0]
    assert top.path == 'src/session.ts'
    assert any(reason.startswith('content matches') for reason in top.reasons)
