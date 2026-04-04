from backend.engine.tools.signal_progress import (
    create_signal_progress_tool,
)
from backend.ledger.action.signal import SignalProgressAction
from backend.ledger.observation.signal import SignalProgressObservation
from backend.orchestration.agent_circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
)


def test_create_signal_progress_tool():
    """Verify the tool schema is correct."""
    tool = create_signal_progress_tool()

    assert tool['type'] == 'function'
    assert tool['function']['name'] == 'signal_progress'

    # Check parameters
    props = tool['function']['parameters']['properties']
    assert 'progress_note' in props
    assert props['progress_note']['type'] == 'string'

    # Check required
    required = tool['function']['parameters']['required']
    assert 'progress_note' in required


def test_signal_progress_action_creation():
    """Verify the action dataclass holds the note."""
    action = SignalProgressAction(progress_note='Refactored 5 files, 3 remaining')
    assert action.action == 'signal_progress'
    assert action.progress_note == 'Refactored 5 files, 3 remaining'


def test_signal_progress_observation_creation():
    """Verify the observation dataclass."""
    obs = SignalProgressObservation(acknowledged=True)
    assert (
        getattr(obs, 'observation_type', None) == 'signal_progress'
        or obs.__class__.__name__ == 'SignalProgressObservation'
    )
    assert obs.acknowledged is True
    # Observation string representation should mention it was acknowledged
    assert 'acknowledged' in str(obs).lower()


def test_circuit_breaker_record_progress_signal():
    """Verify that record_progress_signal decrements stuck_detection_count appropriately."""
    config = CircuitBreakerConfig(
        max_consecutive_errors=10,
        max_high_risk_actions=5,
        max_error_rate=0.8,
        error_rate_window=20,
    )
    cb = CircuitBreaker(config)

    # Setup initial stuck count
    cb.stuck_detection_count = 5

    # Call signal progress
    cb.record_progress_signal('Moving to next batch')

    # Should decrement by 2
    assert cb.stuck_detection_count == 3

    # Call again
    cb.record_progress_signal('Still working')

    # Should decrement by 2
    assert cb.stuck_detection_count == 1

    # Call again, should floor at 0
    cb.record_progress_signal('Almost done')
    assert cb.stuck_detection_count == 0
