"""Stress tests for EventStream persistence_health under load."""

from __future__ import annotations

import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from backend.ledger import EventSource
from backend.ledger.observation.empty import NullObservation
from backend.ledger.stream import EventStream
from backend.persistence.local_file_store import LocalFileStore

pytestmark = pytest.mark.stress


@pytest.fixture
def temp_stream():
    with tempfile.TemporaryDirectory() as tmpdir:
        file_store = LocalFileStore(tmpdir)
        stream = EventStream('persist-health-stress', file_store, worker_count=0)
        try:
            yield stream
        finally:
            stream.close()


def test_rapid_failure_burst_reaches_failed_then_recovers(temp_stream) -> None:
    """Repeated persist failures escalate to failed; success resets to ok."""
    original = temp_stream._persist.persist_event
    state = {'failures': 0}

    def _flaky_persist(*args, **kwargs):
        if state['failures'] < 5:
            state['failures'] += 1
            raise OSError('simulated disk blip')
        return original(*args, **kwargs)

    temp_stream._persist.persist_event = _flaky_persist  # type: ignore[method-assign]

    for idx in range(5):
        temp_stream.add_event(NullObservation(content=f'fail-{idx}'), EventSource.AGENT)
    assert temp_stream.persistence_health == 'failed'

    temp_stream.add_event(NullObservation(content='recover'), EventSource.AGENT)
    assert temp_stream.persistence_health == 'ok'
    assert temp_stream._persist_failure_streak == 0


def test_concurrent_add_event_under_persist_failure_stays_degraded(temp_stream) -> None:
    """Concurrent producers with persist failures must not crash; health stays degraded+."""

    def _always_fail(*_args, **_kwargs):
        raise OSError('disk full')

    temp_stream._persist.persist_event = _always_fail  # type: ignore[method-assign]

    total = 64
    errors: list[Exception] = []
    lock = threading.Lock()

    def _produce(idx: int) -> int:
        try:
            temp_stream.add_event(
                NullObservation(content=f'concurrent-{idx}'),
                EventSource.AGENT,
            )
            return idx
        except Exception as exc:
            with lock:
                errors.append(exc)
            raise

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_produce, i) for i in range(total)]
        for future in as_completed(futures):
            future.result(timeout=10)

    assert not errors
    assert temp_stream.persistence_health in ('degraded', 'failed')
    assert temp_stream._persist_failure_streak >= 3
