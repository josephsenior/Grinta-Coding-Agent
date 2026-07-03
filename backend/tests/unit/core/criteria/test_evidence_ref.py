"""Tests for acceptance-criteria evidence_ref resolution."""

from __future__ import annotations

import pytest

from backend.core.criteria.evidence_ref import (
    EvidenceRefError,
    apply_line_slice,
    parse_evidence_ref,
    resolve_evidence_ref,
)
from backend.ledger.infra.tool import ToolCallMetadata
from backend.ledger.observation import Observation


class _FakeMeta:
    tool_call_id = 'call_test_1'


def test_parse_event_ref_with_line_slice():
    parsed = parse_evidence_ref('event:42:lines[2-4]')
    assert parsed.event_id == 42
    assert parsed.line_start == 2
    assert parsed.line_end == 4


def test_parse_tool_call_ref():
    parsed = parse_evidence_ref('call_abc123:lines[10]')
    assert parsed.event_id is None
    assert parsed.lookup_key == 'call_abc123'
    assert parsed.line_start == 10
    assert parsed.line_end == 10


def test_apply_line_slice():
    content = 'one\ntwo\nthree\nfour'
    assert apply_line_slice(content, 2, 3) == 'two\nthree'


def test_resolve_by_event_id():
    obs = Observation(content='alpha\nbeta\ngamma')
    obs.id = 99
    resolved = resolve_evidence_ref('event:99:lines[2]', [obs])
    assert resolved == 'beta'


def test_resolve_by_tool_call_id():
    obs = Observation(content='tool output here')
    obs.tool_call_metadata = ToolCallMetadata(
        function_name='run',
        tool_call_id='call_xyz',
        model_response={},
        total_calls_in_response=1,
    )
    resolved = resolve_evidence_ref('call_xyz', [obs])
    assert resolved == 'tool output here'


def test_resolve_missing_ref_raises():
    with pytest.raises(EvidenceRefError, match='no matching tool output'):
        resolve_evidence_ref('call_missing', [])
