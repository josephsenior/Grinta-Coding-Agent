"""Tests for playbook trigger matching (strict vs fuzzy tier)."""

from __future__ import annotations

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


def test_strict_disables_word_overlap_tier() -> None:
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


def test_word_overlap_tier_when_not_strict() -> None:
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
