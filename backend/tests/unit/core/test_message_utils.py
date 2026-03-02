"""Tests for backend.core.message_utils — event token usage metadata helpers."""

from typing import Any, cast
from unittest.mock import MagicMock


from backend.core.message_utils import (
    _find_event_index_by_id,
    _find_usage_by_response_id,
    _get_tool_response_id,
    _search_backwards_for_token_usage,
    get_token_usage_for_event,
    get_token_usage_for_event_id,
)


class TestGetToolResponseId:
    """Tests for _get_tool_response_id helper."""

    def test_no_tool_call_metadata(self):
        """Test event without tool_call_metadata returns None."""
        event = MagicMock()
        event.tool_call_metadata = None
        assert _get_tool_response_id(event) is None

    def test_no_model_response(self):
        """Test event with metadata but no model_response returns None."""
        event = MagicMock()
        event.tool_call_metadata = MagicMock()
        event.tool_call_metadata.model_response = None
        assert _get_tool_response_id(event) is None

    def test_with_response_id(self):
        """Test event with model_response containing id."""
        event = MagicMock()
        event.tool_call_metadata = MagicMock()
        event.tool_call_metadata.model_response = {"id": "resp_123"}
        assert _get_tool_response_id(event) == "resp_123"

    def test_missing_id_key(self):
        """Test model_response without id key returns None."""
        event = MagicMock()
        event.tool_call_metadata = MagicMock()
        event.tool_call_metadata.model_response = {"other": "value"}
        assert _get_tool_response_id(event) is None


class TestFindUsageByResponseId:
    """Tests for _find_usage_by_response_id helper."""

    def test_empty_metrics(self):
        """Test with empty token_usages list."""
        metrics = MagicMock()
        metrics.token_usages = []
        assert _find_usage_by_response_id(metrics, "resp_123") is None

    def test_matching_response_id(self):
        """Test finding usage with matching response_id."""
        usage1 = MagicMock()
        usage1.response_id = "resp_100"
        usage2 = MagicMock()
        usage2.response_id = "resp_123"
        usage3 = MagicMock()
        usage3.response_id = "resp_456"

        metrics = MagicMock()
        metrics.token_usages = [usage1, usage2, usage3]

        result = _find_usage_by_response_id(metrics, "resp_123")
        assert result is usage2

    def test_no_matching_response_id(self):
        """Test when no usage matches the response_id."""
        usage1 = MagicMock()
        usage1.response_id = "resp_100"
        usage2 = MagicMock()
        usage2.response_id = "resp_200"

        metrics = MagicMock()
        metrics.token_usages = [usage1, usage2]

        result = _find_usage_by_response_id(metrics, "resp_999")
        assert result is None

    def test_returns_first_match(self):
        """Test returns first matching usage when multiple exist."""
        usage1 = MagicMock()
        usage1.response_id = "resp_123"
        usage2 = MagicMock()
        usage2.response_id = "resp_123"

        metrics = MagicMock()
        metrics.token_usages = [usage1, usage2]

        result = _find_usage_by_response_id(metrics, "resp_123")
        assert result is usage1


class TestGetTokenUsageForEvent:
    """Tests for get_token_usage_for_event function."""

    def test_none_event(self):
        """Test with None event returns None."""
        metrics = MagicMock()
        assert get_token_usage_for_event(None, metrics) is None

    def test_none_metrics(self):
        """Test with None metrics returns None."""
        event = MagicMock()
        assert get_token_usage_for_event(event, None) is None

    def test_both_none(self):
        """Test with both None returns None."""
        assert get_token_usage_for_event(None, None) is None

    def test_finds_by_tool_response_id(self):
        """Test finds usage by tool_call_metadata response id."""
        usage = MagicMock()
        usage.response_id = "resp_tool_123"

        event = MagicMock()
        event.tool_call_metadata = MagicMock()
        event.tool_call_metadata.model_response = {"id": "resp_tool_123"}
        event.response_id = "resp_fallback"

        metrics = MagicMock()
        metrics.token_usages = [usage]

        result = get_token_usage_for_event(event, metrics)
        assert result is usage

    def test_fallback_to_event_response_id(self):
        """Test falls back to event.response_id when tool response id not found."""
        usage = MagicMock()
        usage.response_id = "resp_event_456"

        event = MagicMock()
        event.tool_call_metadata = MagicMock()
        event.tool_call_metadata.model_response = {"id": "resp_not_found"}
        event.response_id = "resp_event_456"

        metrics = MagicMock()
        metrics.token_usages = [usage]

        result = get_token_usage_for_event(event, metrics)
        assert result is usage

    def test_no_match_returns_none(self):
        """Test returns None when no matching usage found."""
        usage = MagicMock()
        usage.response_id = "resp_other"

        event = MagicMock()
        event.tool_call_metadata = None
        event.response_id = "resp_not_found"

        metrics = MagicMock()
        metrics.token_usages = [usage]

        result = get_token_usage_for_event(event, metrics)
        assert result is None

    def test_no_response_id_attribute(self):
        """Test event without response_id attribute."""
        event = MagicMock(spec=[])  # Empty spec means no attributes
        event.tool_call_metadata = None

        metrics = MagicMock()
        metrics.token_usages = []

        result = get_token_usage_for_event(event, metrics)
        assert result is None

    def test_prefers_tool_response_over_event_response(self):
        """Test tool response id is preferred over event response id."""
        usage_tool = MagicMock()
        usage_tool.response_id = "resp_tool"
        usage_event = MagicMock()
        usage_event.response_id = "resp_event"

        event = MagicMock()
        event.tool_call_metadata = MagicMock()
        event.tool_call_metadata.model_response = {"id": "resp_tool"}
        event.response_id = "resp_event"

        metrics = MagicMock()
        metrics.token_usages = [usage_tool, usage_event]

        result = get_token_usage_for_event(event, metrics)
        assert result is usage_tool


class TestFindEventIndexById:
    """Tests for _find_event_index_by_id helper."""

    def test_empty_events_list(self):
        """Test with empty events list."""
        assert _find_event_index_by_id([], 123) is None

    def test_event_found_at_start(self):
        """Test finding event at index 0."""
        event1 = MagicMock()
        event1.id = 100
        event2 = MagicMock()
        event2.id = 200

        assert _find_event_index_by_id([event1, event2], 100) == 0

    def test_event_found_at_end(self):
        """Test finding event at last index."""
        event1 = MagicMock()
        event1.id = 100
        event2 = MagicMock()
        event2.id = 200
        event3 = MagicMock()
        event3.id = 300

        assert _find_event_index_by_id([event1, event2, event3], 300) == 2

    def test_event_found_in_middle(self):
        """Test finding event in middle."""
        events: list[Any] = [MagicMock() for _ in range(5)]
        for i, event in enumerate(events):
            event.id = i * 10

        assert _find_event_index_by_id(events, 20) == 2

    def test_event_not_found(self):
        """Test when event id doesn't exist."""
        event1 = MagicMock()
        event1.id = 100
        event2 = MagicMock()
        event2.id = 200

        assert _find_event_index_by_id([event1, event2], 999) is None


class TestSearchBackwardsForTokenUsage:
    """Tests for _search_backwards_for_token_usage helper."""

    def test_finds_usage_at_start_index(self):
        """Test finding usage at the starting index."""
        usage = MagicMock()
        usage.response_id = "resp_123"

        event = MagicMock()
        event.tool_call_metadata = MagicMock()
        event.tool_call_metadata.model_response = {"id": "resp_123"}

        metrics = MagicMock()
        metrics.token_usages = [usage]

        events: list[Any] = [event]
        result = _search_backwards_for_token_usage(events, 0, metrics)
        assert result is usage

    def test_searches_backwards(self):
        """Test searches backwards from start_idx."""
        usage = MagicMock()
        usage.response_id = "resp_100"

        event0 = MagicMock()
        event0.tool_call_metadata = MagicMock()
        event0.tool_call_metadata.model_response = {"id": "resp_100"}

        event1 = MagicMock()
        event1.tool_call_metadata = None

        event2 = MagicMock()
        event2.tool_call_metadata = None

        metrics = MagicMock()
        metrics.token_usages = [usage]

        events: list[Any] = [event0, event1, event2]
        # Start at index 2, should find usage at index 0
        result = _search_backwards_for_token_usage(events, 2, metrics)
        assert result is usage

    def test_no_usage_found(self):
        """Test returns None when no usage found."""
        event1 = MagicMock()
        event1.tool_call_metadata = None
        event1.response_id = "resp_not_found"

        event2 = MagicMock()
        event2.tool_call_metadata = None
        event2.response_id = "resp_other"

        metrics = MagicMock()
        metrics.token_usages = []

        events: list[Any] = [event1, event2]
        result = _search_backwards_for_token_usage(events, 1, metrics)
        assert result is None

    def test_stops_at_zero_index(self):
        """Test search stops at index 0."""
        event0 = MagicMock()
        event0.tool_call_metadata = None

        events: list[Any] = [event0]
        metrics = MagicMock()
        metrics.token_usages = []

        result = _search_backwards_for_token_usage(events, 0, metrics)
        assert result is None


class TestGetTokenUsageForEventId:
    """Tests for get_token_usage_for_event_id function."""

    def test_event_not_found(self):
        """Test when event id doesn't exist in events list."""
        event1 = MagicMock()
        event1.id = 100

        metrics = MagicMock()

        result = get_token_usage_for_event_id([event1], 999, metrics)
        assert result is None

    def test_none_metrics(self):
        """Test with None metrics returns None."""
        event1 = MagicMock()
        event1.id = 100

        result = get_token_usage_for_event_id([event1], 100, None)
        assert result is None

    def test_finds_usage_for_target_event(self):
        """Test finds usage for the target event."""
        usage = MagicMock()
        usage.response_id = "resp_200"

        event1 = MagicMock()
        event1.id = 100
        event1.tool_call_metadata = None

        event2 = MagicMock()
        event2.id = 200
        event2.tool_call_metadata = MagicMock()
        event2.tool_call_metadata.model_response = {"id": "resp_200"}

        metrics = MagicMock()
        metrics.token_usages = [usage]

        events: list[Any] = [event1, event2]
        result = get_token_usage_for_event_id(events, 200, metrics)
        assert result is usage

    def test_searches_backwards_from_target(self):
        """Test searches backwards from target event."""
        usage = MagicMock()
        usage.response_id = "resp_100"

        event1 = MagicMock()
        event1.id = 100
        event1.tool_call_metadata = MagicMock()
        event1.tool_call_metadata.model_response = {"id": "resp_100"}

        event2 = MagicMock()
        event2.id = 200
        event2.tool_call_metadata = None

        event3 = MagicMock()
        event3.id = 300
        event3.tool_call_metadata = None

        metrics = MagicMock()
        metrics.token_usages = [usage]

        events: list[Any] = [event1, event2, event3]
        # Search from event 300 should find usage from event 100
        result = get_token_usage_for_event_id(events, 300, metrics)
        assert result is usage

    def test_empty_events_list(self):
        """Test with empty events list."""
        metrics = MagicMock()
        result = get_token_usage_for_event_id([], 100, metrics)
        assert result is None

    def test_integration_full_workflow(self):
        """Test full workflow with multiple events."""
        usage1 = MagicMock()
        usage1.response_id = "resp_100"
        usage2 = MagicMock()
        usage2.response_id = "resp_300"

        event1 = MagicMock()
        event1.id = 100
        event1.tool_call_metadata = MagicMock()
        event1.tool_call_metadata.model_response = {"id": "resp_100"}

        event2 = MagicMock()
        event2.id = 200
        event2.tool_call_metadata = None

        event3 = MagicMock()
        event3.id = 300
        event3.tool_call_metadata = MagicMock()
        event3.tool_call_metadata.model_response = {"id": "resp_300"}

        event4 = MagicMock()
        event4.id = 400
        event4.tool_call_metadata = None

        metrics = MagicMock()
        metrics.token_usages = [usage1, usage2]

        events: list[Any] = [event1, event2, event3, event4]

        # Event 400 should find usage from event 300
        result = get_token_usage_for_event_id(events, 400, metrics)
        assert result is usage2

        # Event 200 should find usage from event 100
        result2 = get_token_usage_for_event_id(events, 200, metrics)
        assert result2 is usage1
