"""Unit tests for ProjectMemoryService and Markdown memory parsing."""

from __future__ import annotations

from backend.context.memory.project_memory import (
    ProjectMemoryService,
    _facts_are_similar,
    parse_markdown_memory,
    serialize_markdown_memory,
)


def test_parse_and_serialize_markdown_memory():
    raw_md = """# Grinta Project Memory

## mem-001 · command · active

**Fact:** uv run pytest backend/tests/unit -q

**Evidence:**
- Command run passed on windows
- Confirmed cross-platform

**Created:** 2026-07-10T16:00:00Z
**Last verified:** 2026-07-10T16:05:00Z
**Confidence:** 0.95
**Source sessions:** session-123
**Superseded by:** mem-002

---
"""
    entries = parse_markdown_memory(raw_md)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.id == 'mem-001'
    assert entry.kind == 'command'
    assert entry.status == 'active'
    assert entry.fact == 'uv run pytest backend/tests/unit -q'
    assert len(entry.evidence) == 2
    assert entry.evidence[0] == 'Command run passed on windows'
    assert entry.confidence == 0.95
    assert entry.source_sessions == ['session-123']
    assert entry.superseded_by == ['mem-002']

    serialized = serialize_markdown_memory(entries)
    assert '## mem-001 · command · active' in serialized
    assert '**Fact:** uv run pytest backend/tests/unit -q' in serialized
    assert '**Confidence:** 0.95' in serialized


def test_facts_are_similar():
    assert (
        _facts_are_similar(
            'Run integration tests with uv run pytest backend/tests/integration -q.',
            'Run integration tests with uv run pytest backend/tests/integration',
        )
        is True
    )

    assert (
        _facts_are_similar(
            'Run integration tests with uv run pytest backend/tests/integration -q.',
            'Create a new file in app/main.py',
        )
        is False
    )


def test_project_memory_service_upsert(tmp_path):
    service = ProjectMemoryService(workspace_root=tmp_path)

    # 1. First upsert creates new entry
    id1 = service.upsert_candidate(
        kind='command',
        fact='uv run pytest backend/tests/unit -q',
        evidence=['passed'],
        confidence=0.9,
        source_session='session-a',
    )
    assert id1 == 'mem-001'

    entries = service.load()
    assert len(entries) == 1
    assert entries[0].fact == 'uv run pytest backend/tests/unit -q'

    # 2. Similar upsert merges
    id2 = service.upsert_candidate(
        kind='command',
        fact='uv run pytest backend/tests/unit',
        evidence=['passed again'],
        confidence=0.95,
        source_session='session-b',
    )
    assert id2 == 'mem-001'

    entries = service.load()
    assert len(entries) == 1
    assert 'passed again' in entries[0].evidence
    assert entries[0].confidence == 0.95

    # 3. Different upsert creates new sequential entry
    id3 = service.upsert_candidate(
        kind='convention',
        fact='Use absolute imports in python files',
        evidence=['convention checklist'],
        confidence=0.88,
        source_session='session-c',
    )
    assert id3 == 'mem-002'
