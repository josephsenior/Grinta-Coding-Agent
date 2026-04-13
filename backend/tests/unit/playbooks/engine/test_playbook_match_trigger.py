"""Tests for playbook trigger matching under explicit and auto-trigger modes."""

from __future__ import annotations

import backend.playbooks.engine.playbook as playbook_module
from backend.playbooks.engine.playbook import KnowledgePlaybook
from backend.playbooks.engine.types import PlaybookMetadata, PlaybookType


def test_substring_trigger_always_matches() -> None:
    pb = KnowledgePlaybook(
        name='kb',
        content='body',
        metadata=PlaybookMetadata(
            name='kb',
            type=PlaybookType.KNOWLEDGE,
            triggers=['/deploy'],
            strict_trigger_matching=True,
        ),
        source='.',
        type=PlaybookType.KNOWLEDGE,
    )
    assert pb.match_trigger('please /deploy now') == '/deploy'


def test_non_slash_trigger_blocked_when_auto_disabled() -> None:
    pb = KnowledgePlaybook(
        name='kb',
        content='body',
        metadata=PlaybookMetadata(
            name='kb',
            type=PlaybookType.KNOWLEDGE,
            triggers=['deploy help'],
            strict_trigger_matching=False,
        ),
        source='.',
        type=PlaybookType.KNOWLEDGE,
    )
    assert pb.match_trigger('can you deploy help docs now?') is None


def test_strict_disables_word_overlap_tier(monkeypatch) -> None:
    monkeypatch.setattr(playbook_module, 'AUTO_TRIGGER_ENABLED', True)
    pb = KnowledgePlaybook(
        name='kb',
        content='body',
        metadata=PlaybookMetadata(
            name='kb',
            type=PlaybookType.KNOWLEDGE,
            triggers=['deploy help'],
            strict_trigger_matching=True,
        ),
        source='.',
        type=PlaybookType.KNOWLEDGE,
    )
    # Words overlap but full trigger substring is not present.
    assert pb.match_trigger('help me deploy my application') is None


def test_word_overlap_tier_when_auto_enabled(monkeypatch) -> None:
    monkeypatch.setattr(playbook_module, 'AUTO_TRIGGER_ENABLED', True)
    pb = KnowledgePlaybook(
        name='kb',
        content='body',
        metadata=PlaybookMetadata(
            name='kb',
            type=PlaybookType.KNOWLEDGE,
            triggers=['deploy help'],
            strict_trigger_matching=False,
        ),
        source='.',
        type=PlaybookType.KNOWLEDGE,
    )
    assert pb.match_trigger('help me deploy my application') == 'deploy help'


def test_roasted_review_alias_trigger_matches() -> None:
    pb = KnowledgePlaybook(
        name='code_review',
        content='body',
        metadata=PlaybookMetadata(
            name='code_review',
            type=PlaybookType.KNOWLEDGE,
            triggers=['/codereview', '/codereview-roasted'],
            strict_trigger_matching=True,
        ),
        source='.',
        type=PlaybookType.KNOWLEDGE,
    )
    assert pb.match_trigger('please run /codereview-roasted now') == '/codereview-roasted'
