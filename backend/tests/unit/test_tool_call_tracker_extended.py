"""Tests for backend.memory.tool_call_tracker – stateless helpers (extended)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from backend.core.message import Message, TextContent, ToolCall, ToolCallFunction
from backend.memory.tool_call_tracker import (
    collect_tool_call_ids,
    collect_tool_response_ids,
    filter_unmatched_tool_calls,
    flush_resolved_tool_calls,
)


@dataclass
class _FakeToolState:
    pending_action_messages: dict[str, Message] = field(default_factory=dict)
    tool_call_messages: dict[str, Message] = field(default_factory=dict)


def _tc(call_id: str, name: str = "fn") -> ToolCall:
    return ToolCall(id=call_id, function=ToolCallFunction(name=name, arguments="{}"))


def _assistant_msg(*tool_calls: ToolCall) -> Message:
    return Message(
        role="assistant",
        content=[TextContent(text="ok")],
        tool_calls=list(tool_calls),
    )


def _tool_msg(call_id: str) -> Message:
    return Message(
        role="tool",
        content=[TextContent(text="result")],
        tool_call_id=call_id,
        name="fn",
    )


# ── collect_tool_call_ids ────────────────────────────────────────────

class TestCollectToolCallIdsExtended:
    def test_empty(self):
        assert collect_tool_call_ids([]) == set()

    def test_collects_from_assistant(self):
        msgs = [_assistant_msg(_tc("tc1"), _tc("tc2"))]
        assert collect_tool_call_ids(msgs) == {"tc1", "tc2"}

    def test_ignores_non_assistant(self):
        msg = Message(
            role="user",
            content=[TextContent(text="hi")],
            tool_calls=[_tc("tc1")],
        )
        assert collect_tool_call_ids([msg]) == set()

    def test_multiple_messages(self):
        msgs = [_assistant_msg(_tc("a1")), _assistant_msg(_tc("a2"))]
        assert collect_tool_call_ids(msgs) == {"a1", "a2"}


# ── collect_tool_response_ids ────────────────────────────────────────

class TestCollectToolResponseIdsExtended:
    def test_empty(self):
        assert collect_tool_response_ids([]) == set()

    def test_collects(self):
        msgs = [_tool_msg("tc1"), _tool_msg("tc2")]
        assert collect_tool_response_ids(msgs) == {"tc1", "tc2"}


# ── flush_resolved_tool_calls ────────────────────────────────────────

class TestFlushResolvedExtended:
    def test_no_pending(self):
        state = _FakeToolState()
        assert flush_resolved_tool_calls(state) == []

    def test_flushes_when_resolved(self):
        tc = _tc("tc1")
        pending = _assistant_msg(tc)
        resp = _tool_msg("tc1")
        state = _FakeToolState(
            pending_action_messages={"r1": pending},
            tool_call_messages={"tc1": resp},
        )
        result = flush_resolved_tool_calls(state)
        assert len(result) == 2
        assert "r1" not in state.pending_action_messages

    def test_multi_tool_call_resolved(self):
        tc1 = _tc("tc1")
        tc2 = _tc("tc2")
        pending = _assistant_msg(tc1, tc2)
        state = _FakeToolState(
            pending_action_messages={"r1": pending},
            tool_call_messages={"tc1": _tool_msg("tc1"), "tc2": _tool_msg("tc2")},
        )
        result = flush_resolved_tool_calls(state)
        assert len(result) == 3  # pending + 2 tool responses


# ── filter_unmatched_tool_calls ──────────────────────────────────────

class TestFilterUnmatchedExtended:
    def test_pass_through(self):
        msgs = [Message(role="user", content=[TextContent(text="hi")])]
        assert len(list(filter_unmatched_tool_calls(msgs))) == 1

    def test_matched_pair(self):
        msgs = [_assistant_msg(_tc("tc1")), _tool_msg("tc1")]
        result = list(filter_unmatched_tool_calls(msgs))
        assert len(result) == 2

    def test_orphan_tool_excluded(self):
        msgs = [_tool_msg("orphan")]
        assert len(list(filter_unmatched_tool_calls(msgs))) == 0
