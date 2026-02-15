import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.events import EventSource, EventStream
from backend.events.observation import NullObservation
from backend.storage import get_file_store

pytestmark = pytest.mark.stress


@pytest.fixture
def temp_stream(tmp_path, monkeypatch):
    """Yield an EventStream backed by a temp directory with async persistence forced on."""
    monkeypatch.setenv("FORGE_EVENTSTREAM_ASYNC_WRITE", "true")
    file_store = get_file_store("local", str(tmp_path))
    stream = EventStream("stress-session", file_store)
    try:
        yield stream
    finally:
        stream.close()


def test_async_writer_keeps_add_event_fast(temp_stream, monkeypatch):
    """Slow file writes should not significantly impact add_event latency."""
    file_store = temp_stream.file_store
    original_write = file_store.write

    write_calls = 0
    write_lock = threading.Lock()

    def slow_write(filename, content):
        nonlocal write_calls
        with write_lock:
            write_calls += 1
        time.sleep(0.02)
        return original_write(filename, content)

    monkeypatch.setattr(file_store, "write", slow_write)

    total_events = 80
    start = time.perf_counter()
    for idx in range(total_events):
        temp_stream.add_event(NullObservation(f"payload-{idx}"), EventSource.AGENT)
    duration = time.perf_counter() - start

    # Without async persistence this would be ~1.6s (80 * 0.02).
    assert duration < 0.4, f"add_event took too long: {duration:.3f}s"

    # Ensure writer eventually flushes every event (allow some slack).
    deadline = time.time() + 5
    while (
        temp_stream._durable_writer and not temp_stream._durable_writer._queue.empty()
    ):
        assert time.time() < deadline, "Durable writer did not drain in time"
        time.sleep(0.05)

    assert write_calls >= total_events  # cache writes add extras


def test_event_stream_handles_parallel_producers(temp_stream):
    """Concurrent producers should add events without dropping under default settings."""
    total_events = 120
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(
                temp_stream.add_event,
                NullObservation(f"parallel-{idx}"),
                EventSource.AGENT,
            )
            for idx in range(total_events)
        ]
        for future in futures:
            future.result(timeout=2)

    events = temp_stream.get_matching_events()
    assert len(events) == total_events
