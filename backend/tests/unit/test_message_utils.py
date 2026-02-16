"""Tests for backend.core.message_utils — event token-usage helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.core.message_utils import (
    _find_event_index_by_id,
    _search_backwards_for_token_usage,
    get_token_usage_for_event,
    get_token_usage_for_event_id,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _usage(response_id: str = "r1", prompt: int = 10, completion: int = 5):
    return SimpleNamespace(response_id=response_id, prompt_tokens=prompt, completion_tokens=completion)


def _metrics(usages: list | None = None):
    return SimpleNamespace(token_usages=usages or [])


def _event(eid: int = 1, response_id: str | None = None, tool_meta=None):
    e = SimpleNamespace(id=eid, response_id=response_id, tool_call_metadata=tool_meta)
    return e


def _tool_meta(model_response_id: str | None = None):
    mr = {"id": model_response_id} if model_response_id else None
    return SimpleNamespace(model_response=mr)


# ===================================================================
# _find_event_index_by_id
# ===================================================================

class TestFindEventIndexById:

    def test_found(self):
        events = [_event(10), _event(20), _event(30)]
        assert _find_event_index_by_id(events, 20) == 1

    def test_not_found(self):
        events = [_event(1), _event(2)]
        assert _find_event_index_by_id(events, 99) is None

    def test_empty_list(self):
        assert _find_event_index_by_id([], 1) is None


# ===================================================================
# get_token_usage_for_event
# ===================================================================

class TestGetTokenUsageForEvent:

    def test_none_event(self):
        assert get_token_usage_for_event(None, _metrics()) is None

    def test_none_metrics(self):
        assert get_token_usage_for_event(_event(), None) is None

    def test_via_tool_call_metadata(self):
        u = _usage(response_id="tool-resp")
        m = _metrics([u])
        e = _event(tool_meta=_tool_meta(model_response_id="tool-resp"))
        result = get_token_usage_for_event(e, m)
        assert result is u

    def test_via_event_response_id_fallback(self):
        u = _usage(response_id="fallback-id")
        m = _metrics([u])
        e = _event(response_id="fallback-id", tool_meta=None)
        result = get_token_usage_for_event(e, m)
        assert result is u

    def test_neither_match(self):
        m = _metrics([_usage(response_id="other")])
        e = _event(response_id="nope", tool_meta=None)
        assert get_token_usage_for_event(e, m) is None

    def test_tool_meta_with_no_model_response(self):
        m = _metrics([_usage(response_id="x")])
        e = _event(response_id="x", tool_meta=SimpleNamespace(model_response=None))
        result = get_token_usage_for_event(e, m)
        assert result is not None  # falls back to event.response_id


# ===================================================================
# get_token_usage_for_event_id
# ===================================================================

class TestGetTokenUsageForEventId:

    def test_finds_usage_at_exact_event(self):
        u = _usage(response_id="resp-20")
        events = [
            _event(10, response_id="resp-10", tool_meta=None),
            _event(20, response_id="resp-20", tool_meta=None),
        ]
        result = get_token_usage_for_event_id(events, 20, _metrics([u]))
        assert result is u

    def test_searches_backwards(self):
        u = _usage(response_id="resp-10")
        events = [
            _event(10, response_id="resp-10", tool_meta=None),
            _event(20, response_id=None, tool_meta=None),
        ]
        result = get_token_usage_for_event_id(events, 20, _metrics([u]))
        assert result is u

    def test_event_not_found(self):
        assert get_token_usage_for_event_id([_event(1)], 999, _metrics()) is None

    def test_none_metrics(self):
        events = [_event(1)]
        assert get_token_usage_for_event_id(events, 1, None) is None

    def test_no_usage_found(self):
        events = [_event(1, response_id=None, tool_meta=None)]
        result = get_token_usage_for_event_id(events, 1, _metrics([]))
        assert result is None
