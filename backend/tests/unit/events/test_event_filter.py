"""Tests for backend.events.event_filter — event stream filtering utilities."""

from __future__ import annotations



from backend.events.action.message import MessageAction
from backend.events.event_filter import EventFilter
from backend.events.observation import NullObservation


# ── EventFilter dataclass ──────────────────────────────────────────────


class TestEventFilterCreation:
    """Test EventFilter creation and defaults."""

    def test_creates_with_defaults(self):
        """Test creating EventFilter with default values."""
        filter = EventFilter()
        assert filter.exclude_hidden is False
        assert filter.query is None
        assert filter.include_types is None
        assert filter.exclude_types is None
        assert filter.source is None
        assert filter.start_date is None
        assert filter.end_date is None

    def test_creates_with_custom_values(self):
        """Test creating EventFilter with custom values."""
        filter = EventFilter(
            exclude_hidden=True,
            query="test",
            include_types=(MessageAction,),
            source="agent",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        assert filter.exclude_hidden is True
        assert filter.query == "test"
        assert filter.include_types == (MessageAction,)
        assert filter.source == "agent"
        assert filter.start_date == "2024-01-01"
        assert filter.end_date == "2024-12-31"


# ── include method ─────────────────────────────────────────────────────


class TestEventFilterInclude:
    """Test EventFilter.include method."""

    def test_includes_event_with_no_filters(self):
        """Test includes all events when no filters are set."""
        filter = EventFilter()
        event = MessageAction(content="test")

        assert filter.include(event) is True

    def test_filters_by_include_types(self):
        """Test filters by include_types."""
        filter = EventFilter(include_types=(MessageAction,))

        message_event = MessageAction(content="test")
        null_event = NullObservation(content="")

        assert filter.include(message_event) is True
        assert filter.include(null_event) is False

    def test_filters_by_exclude_types(self):
        """Test filters by exclude_types."""
        filter = EventFilter(exclude_types=(NullObservation,))

        message_event = MessageAction(content="test")
        null_event = NullObservation(content="")

        assert filter.include(message_event) is True
        assert filter.include(null_event) is False

    def test_filters_by_source(self):
        """Test filters by event source."""
        from backend.core.enums import EventSource

        filter = EventFilter(source="agent")

        agent_event = MessageAction(content="test")
        agent_event.source = EventSource.AGENT

        user_event = MessageAction(content="test")
        user_event.source = EventSource.USER

        no_source_event = MessageAction(content="test")
        no_source_event.source = None

        assert filter.include(agent_event) is True
        assert filter.include(user_event) is False
        assert filter.include(no_source_event) is False

    def test_filters_by_start_date(self):
        """Test filters by start_date."""
        filter = EventFilter(start_date="2024-06-01")

        early_event = MessageAction(content="early")
        early_event._timestamp = "2024-05-01"

        later_event = MessageAction(content="later")
        later_event._timestamp = "2024-07-01"

        assert filter.include(early_event) is False
        assert filter.include(later_event) is True

    def test_filters_by_end_date(self):
        """Test filters by end_date."""
        filter = EventFilter(end_date="2024-06-30")

        early_event = MessageAction(content="early")
        early_event._timestamp = "2024-06-15"

        later_event = MessageAction(content="later")
        later_event._timestamp = "2024-07-15"

        assert filter.include(early_event) is True
        assert filter.include(later_event) is False

    def test_filters_by_date_range(self):
        """Test filters by start and end date."""
        filter = EventFilter(start_date="2024-06-01", end_date="2024-06-30")

        before_event = MessageAction(content="before")
        before_event._timestamp = "2024-05-15"

        during_event = MessageAction(content="during")
        during_event._timestamp = "2024-06-15"

        after_event = MessageAction(content="after")
        after_event._timestamp = "2024-07-15"

        assert filter.include(before_event) is False
        assert filter.include(during_event) is True
        assert filter.include(after_event) is False

    def test_includes_events_without_timestamp_in_date_filter(self):
        """Test includes events without timestamp when date filters are set."""
        filter = EventFilter(start_date="2024-01-01")

        event = MessageAction(content="test")
        event.timestamp = None

        assert filter.include(event) is True

    def test_filters_by_hidden_attribute(self):
        """Test filters by hidden attribute when exclude_hidden is True."""
        filter = EventFilter(exclude_hidden=True)

        visible_event = MessageAction(content="visible")
        # No hidden attribute means not hidden

        hidden_event = MessageAction(content="hidden")
        hidden_event.hidden = True

        non_hidden_event = MessageAction(content="non-hidden")
        non_hidden_event.hidden = False

        assert filter.include(visible_event) is True
        assert filter.include(hidden_event) is False
        assert filter.include(non_hidden_event) is True

    def test_filters_by_query_text(self):
        """Test filters by query text in event content."""
        filter = EventFilter(query="important")

        matching_event = MessageAction(content="This is important")
        non_matching_event = MessageAction(content="Just a regular message")

        assert filter.include(matching_event) is True
        assert filter.include(non_matching_event) is False

    def test_query_is_case_insensitive(self):
        """Test query matching is case-insensitive."""
        filter = EventFilter(query="IMPORTANT")

        event = MessageAction(content="This is important")

        assert filter.include(event) is True

    def test_query_searches_full_event_json(self):
        """Test query searches through entire event JSON representation."""
        filter = EventFilter(query="secret_field")

        # Event with field that matches query
        event = MessageAction(content="test")
        # Query will search through event_to_dict output
        # Since MessageAction doesn't have "secret_field", it won't match

        assert filter.include(event) is False

    def test_combines_multiple_filters(self):
        """Test combines multiple filter criteria (all must pass)."""
        from backend.core.enums import EventSource

        filter = EventFilter(
            include_types=(MessageAction,),
            source="agent",
            start_date="2024-01-01",
            query="important",
        )

        # Passes all criteria
        matching_event = MessageAction(content="important message")
        matching_event.source = EventSource.AGENT
        matching_event._timestamp = "2024-06-01"

        # Wrong type
        wrong_type_event = NullObservation(content="")
        wrong_type_event.source = EventSource.AGENT
        wrong_type_event._timestamp = "2024-06-01"

        # Wrong source
        wrong_source_event = MessageAction(content="important message")
        wrong_source_event.source = EventSource.USER
        wrong_source_event._timestamp = "2024-06-01"

        # Wrong date
        wrong_date_event = MessageAction(content="important message")
        wrong_date_event.source = EventSource.AGENT
        wrong_date_event._timestamp = "2023-12-01"

        # Missing query
        wrong_query_event = MessageAction(content="regular message")
        wrong_query_event.source = EventSource.AGENT
        wrong_query_event._timestamp = "2024-06-01"

        assert filter.include(matching_event) is True
        assert filter.include(wrong_type_event) is False
        assert filter.include(wrong_source_event) is False
        assert filter.include(wrong_date_event) is False
        assert filter.include(wrong_query_event) is False


# ── exclude method ─────────────────────────────────────────────────────


class TestEventFilterExclude:
    """Test EventFilter.exclude method."""

    def test_exclude_is_inverse_of_include(self):
        """Test exclude returns opposite of include."""
        filter = EventFilter(include_types=(MessageAction,))

        message_event = MessageAction(content="test")
        null_event = NullObservation(content="")

        assert filter.include(message_event) is True
        assert filter.exclude(message_event) is False

        assert filter.include(null_event) is False
        assert filter.exclude(null_event) is True


# ── Private helper methods ─────────────────────────────────────────────


class TestEventFilterHelpers:
    """Test EventFilter private helper methods."""

    def test_check_type_filters_with_include_types(self):
        """Test _check_type_filters with include_types."""
        filter = EventFilter(include_types=(MessageAction,))

        assert filter._check_type_filters(MessageAction(content="test")) is True
        assert filter._check_type_filters(NullObservation(content="")) is False

    def test_check_type_filters_with_exclude_types(self):
        """Test _check_type_filters with exclude_types."""
        filter = EventFilter(exclude_types=(NullObservation,))

        assert filter._check_type_filters(MessageAction(content="test")) is True
        assert filter._check_type_filters(NullObservation(content="")) is False

    def test_check_type_filters_with_both(self):
        """Test _check_type_filters with both include and exclude."""
        filter = EventFilter(
            include_types=(MessageAction, NullObservation),
            exclude_types=(NullObservation,),
        )

        assert filter._check_type_filters(MessageAction(content="test")) is True
        assert filter._check_type_filters(NullObservation(content="")) is False

    def test_check_source_filter_no_filter_set(self):
        """Test _check_source_filter when no source filter is set."""
        filter = EventFilter()

        event = MessageAction(content="test")
        assert filter._check_source_filter(event) is True

    def test_check_source_filter_with_filter(self):
        """Test _check_source_filter with source filter."""
        from backend.core.enums import EventSource

        filter = EventFilter(source="agent")

        agent_event = MessageAction(content="test")
        agent_event.source = EventSource.AGENT

        assert filter._check_source_filter(agent_event) is True

    def test_check_date_filters_no_timestamp(self):
        """Test _check_date_filters with event lacking timestamp."""
        filter = EventFilter(start_date="2024-01-01")

        event = MessageAction(content="test")
        event.timestamp = None

        assert filter._check_date_filters(event) is True

    def test_check_hidden_filter_no_hidden_attribute(self):
        """Test _check_hidden_filter when event lacks hidden attribute."""
        filter = EventFilter(exclude_hidden=True)

        event = MessageAction(content="test")
        # No hidden attribute

        assert filter._check_hidden_filter(event) is True

    def test_check_query_filter_no_query(self):
        """Test _check_query_filter when no query is set."""
        filter = EventFilter()

        event = MessageAction(content="test")
        assert filter._check_query_filter(event) is True


