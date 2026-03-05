import pytest
from unittest.mock import MagicMock
from backend.api.services.event_query_service import get_contextual_events_text
from backend.core.errors import ReplayError

class MockEvent:
    def __init__(self, id):
        self.id = id
        self.payload = {"text": f"Event {id}"}
    def __str__(self):
        return f"Event {self.id}"

@pytest.fixture
def mock_event_store():
    store = MagicMock()

    def search_events(start_id=0, end_id=None, reverse=False, filter=None, limit=None):
        # Very simple simulation of search_events logic
        if end_id is None:
            end_id = 9 # assumed cur_id-1 in mock

        events = [MockEvent(i) for i in range(10)]

        # normalized range [start_id, end_id] inclusive in this simulation
        # Wait, the real normalize_search_range does end_id = end_id + 1 if not None.
        # So [start_id, end_id] inclusive in common talk.

        results = [e for e in events if start_id <= e.id <= end_id]
        if reverse:
            results.reverse()

        if limit:
            results = results[:limit]
        return results

    store.search_events.side_effect = search_events
    return store

def test_get_contextual_events_text_range(mock_event_store):
    """Test that context is correctly extracted around a midpoint."""
    # Assuming event_id 5, context_size 2
    # Should get: before=(4, 3), after=(5, 6, 7)
    # Total: 3, 4, 5, 6, 7
    result = get_contextual_events_text(
        event_store=mock_event_store,
        event_id=5,
        event_filter=None,
        context_size=2
    )

    # Check lines
    lines = result.split("\n")
    # Expected: Event 3, Event 4, Event 5, Event 6, Event 7
    assert "Event 3" in lines
    assert "Event 4" in lines
    assert "Event 5" in lines
    assert "Event 6" in lines
    assert "Event 7" in lines
    assert len(lines) == 5

def test_get_contextual_events_text_near_start(mock_event_store):
    # event_id 1, context_size 2
    # before=(0), after=(1, 2, 3)
    result = get_contextual_events_text(
        event_store=mock_event_store,
        event_id=1,
        event_filter=None,
        context_size=2
    )
    lines = result.split("\n")
    assert lines[0] == "Event 0"
    assert lines[1] == "Event 1"
    assert len(lines) == 4

def test_get_contextual_events_invalid_inputs(mock_event_store):
    with pytest.raises(ReplayError, match="event_id must be non-negative"):
        get_contextual_events_text(event_store=mock_event_store, event_id=-1, event_filter=None)

    with pytest.raises(ReplayError, match="context_size must be non-negative"):
        get_contextual_events_text(event_store=mock_event_store, event_id=5, event_filter=None, context_size=-1)

def test_get_contextual_events_store_exception(mock_event_store):
    mock_event_store.search_events.side_effect = Exception("Storage failed")
    with pytest.raises(ReplayError, match="Failed to read contextual events: Storage failed"):
        get_contextual_events_text(event_store=mock_event_store, event_id=5, event_filter=None)
