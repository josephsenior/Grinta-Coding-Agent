"""Unit tests for backend.memory.tool_call_tracker — tool-call pairing helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.core.message import Message, TextContent, ToolCall, ToolCallFunction
from backend.memory.tool_call_tracker import (
    _all_tool_calls_match,
    _maybe_trim_tool_calls,
    _should_include_message,
    collect_tool_call_ids,
    collect_tool_response_ids,
    filter_unmatched_tool_calls,
    flush_resolved_tool_calls,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tc(call_id: str, fn_name: str = "do_thing") -> ToolCall:
    """Create a real ToolCall object."""
    return ToolCall(id=call_id, function=ToolCallFunction(name=fn_name, arguments="{}"))


def _msg(
    role: str,
    text: str = "",
    tool_calls=None,
    tool_call_id: str | None = None,
    name: str | None = None,
) -> Message:
    content = [TextContent(text=text)] if text else []
    return Message(
        role=role,
        content=content,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
        name=name,
    )


def _tool_state(pending=None, resolved=None):
    """Create a _ToolCallTracking-compatible namespace."""
    from dataclasses import dataclass, field

    @dataclass
    class _ToolCallTracking:
        pending_action_messages: dict = field(default_factory=dict)
        tool_call_messages: dict = field(default_factory=dict)

    ts = _ToolCallTracking()
    ts.pending_action_messages = pending or {}
    ts.tool_call_messages = resolved or {}
    return ts


# ---------------------------------------------------------------------------
# collect_tool_call_ids
# ---------------------------------------------------------------------------


class TestCollectToolCallIds:
    def test_assistant_messages_collected(self):
        tc1, tc2 = _tc("c1"), _tc("c2")
        msgs = [_msg("assistant", tool_calls=[tc1, tc2])]
        assert collect_tool_call_ids(msgs) == {"c1", "c2"}

    def test_user_messages_ignored(self):
        tc = _tc("c1")
        msgs = [_msg("user", tool_calls=[tc])]
        assert collect_tool_call_ids(msgs) == set()

    def test_empty_messages(self):
        assert collect_tool_call_ids([]) == set()

    def test_none_tool_calls(self):
        msgs = [_msg("assistant")]
        assert collect_tool_call_ids(msgs) == set()


# ---------------------------------------------------------------------------
# collect_tool_response_ids
# ---------------------------------------------------------------------------


class TestCollectToolResponseIds:
    def test_tool_messages_collected(self):
        msgs = [
            _msg("tool", tool_call_id="c1"),
            _msg("tool", tool_call_id="c2"),
        ]
        assert collect_tool_response_ids(msgs) == {"c1", "c2"}

    def test_non_tool_role_ignored(self):
        msgs = [_msg("assistant", tool_call_id="c1")]
        assert collect_tool_response_ids(msgs) == set()

    def test_empty(self):
        assert collect_tool_response_ids([]) == set()


# ---------------------------------------------------------------------------
# _should_include_message
# ---------------------------------------------------------------------------


class TestShouldIncludeMessage:
    def test_tool_with_matching_call(self):
        msg = _msg("tool", tool_call_id="c1")
        assert _should_include_message(msg, {"c1"}, {"c1"}) is True

    def test_tool_without_matching_call(self):
        msg = _msg("tool", tool_call_id="c_orphan")
        assert _should_include_message(msg, {"c1"}, {"c1"}) is False

    def test_assistant_with_all_matched(self):
        tc = _tc("c1")
        msg = _msg("assistant", tool_calls=[tc])
        assert _should_include_message(msg, {"c1"}, {"c1"}) is True

    def test_user_always_included(self):
        msg = _msg("user", text="hello")
        assert _should_include_message(msg, set(), set()) is True


# ---------------------------------------------------------------------------
# _maybe_trim_tool_calls
# ---------------------------------------------------------------------------


class TestMaybeTrimToolCalls:
    def test_no_trimming_when_all_match(self):
        tc = _tc("c1")
        msg = _msg("assistant", tool_calls=[tc])
        result = _maybe_trim_tool_calls(msg, {"c1"})
        assert result.tool_calls == [tc]

    def test_non_assistant_passthrough(self):
        msg = _msg("user", text="hi")
        result = _maybe_trim_tool_calls(msg, set())
        assert result is msg

    def test_trim_unmatched(self):
        tc1, tc2 = _tc("c1"), _tc("c2")
        msg = _msg("assistant", tool_calls=[tc1, tc2])
        result = _maybe_trim_tool_calls(msg, {"c1"})
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id == "c1"

    def test_all_unmatched_raises_stop_iteration(self):
        tc = _tc("c1")
        msg = _msg("assistant", tool_calls=[tc])
        with pytest.raises(StopIteration):
            _maybe_trim_tool_calls(msg, set())


# ---------------------------------------------------------------------------
# _all_tool_calls_match
# ---------------------------------------------------------------------------


class TestAllToolCallsMatch:
    def test_all_match(self):
        tc1, tc2 = _tc("c1"), _tc("c2")
        msg = _msg("assistant", tool_calls=[tc1, tc2])
        assert _all_tool_calls_match(msg, {"c1", "c2"}) is True

    def test_partial_match(self):
        tc1, tc2 = _tc("c1"), _tc("c2")
        msg = _msg("assistant", tool_calls=[tc1, tc2])
        # c2 is missing from responses — but some match, so returns True
        assert _all_tool_calls_match(msg, {"c1"}) is True

    def test_no_match(self):
        tc = _tc("c1")
        msg = _msg("assistant", tool_calls=[tc])
        assert _all_tool_calls_match(msg, {"c_other"}) is False

    def test_no_tool_calls(self):
        msg = _msg("assistant")
        assert _all_tool_calls_match(msg, set()) is True


# ---------------------------------------------------------------------------
# filter_unmatched_tool_calls (integration)
# ---------------------------------------------------------------------------


class TestFilterUnmatchedToolCalls:
    def test_fully_paired(self):
        tc = _tc("c1")
        msgs = [
            _msg("assistant", tool_calls=[tc]),
            _msg("tool", tool_call_id="c1"),
        ]
        result = list(filter_unmatched_tool_calls(msgs))
        assert len(result) == 2

    def test_orphan_tool_response_dropped(self):
        msgs = [
            _msg("user", text="hi"),
            _msg("tool", tool_call_id="c_orphan"),
        ]
        result = list(filter_unmatched_tool_calls(msgs))
        # Orphan tool response without matching assistant call is dropped
        assert len(result) == 1
        assert result[0].role == "user"

    def test_passthrough_user_system(self):
        msgs = [
            _msg("user", text="hello"),
            _msg("system", text="you are helpful"),
        ]
        result = list(filter_unmatched_tool_calls(msgs))
        assert len(result) == 2


# ---------------------------------------------------------------------------
# flush_resolved_tool_calls
# ---------------------------------------------------------------------------


class TestFlushResolvedToolCalls:
    def test_no_pending(self):
        ts = _tool_state()
        result = flush_resolved_tool_calls(ts)
        assert result == []

    def test_resolved_flushed(self):
        tc = _tc("c1")
        pending_msg = _msg("assistant", tool_calls=[tc])
        response_msg = _msg("tool", tool_call_id="c1")

        ts = _tool_state(
            pending={"resp_1": pending_msg},
            resolved={"c1": response_msg},
        )
        result = flush_resolved_tool_calls(ts)
        assert len(result) == 2  # pending + response
        assert ts.pending_action_messages == {}
        assert ts.tool_call_messages == {}

    def test_unresolved_stays_pending(self):
        tc1, tc2 = _tc("c1"), _tc("c2")
        pending_msg = _msg("assistant", tool_calls=[tc1, tc2])
        response_msg = _msg("tool", tool_call_id="c1")

        ts = _tool_state(
            pending={"resp_1": pending_msg},
            resolved={"c1": response_msg},
        )
        result = flush_resolved_tool_calls(ts)
        # c2 not resolved yet → stays pending
        assert len(result) == 0
        assert "resp_1" in ts.pending_action_messages
