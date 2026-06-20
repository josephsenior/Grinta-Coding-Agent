"""Integration tests for reliability lifecycle: pending, drain, persistence."""

from __future__ import annotations

import asyncio
import tempfile
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from backend.ledger import EventSource
from backend.ledger.observation import StatusObservation
from backend.ledger.observation.empty import NullObservation
from backend.ledger.stream import EventStream
from backend.orchestration.health import collect_orchestration_health
from backend.orchestration.mixins.parallel import (
    _SessionOrchestratorParallelMixin,
)
from backend.orchestration.services.pending_action_service import PendingActionService
from backend.persistence.file_store.local_file_store import LocalFileStore
from backend.utils.async_helpers.async_utils import drain_step_barrier, run_or_schedule

pytestmark = pytest.mark.integration


class _DrainStub(_SessionOrchestratorParallelMixin):
    """Minimal object exposing parallel-mixin drain/warning helpers."""


def _make_pending_service() -> PendingActionService:
    ctx = MagicMock()
    ctx.get_controller.return_value = MagicMock(event_stream=MagicMock())
    return PendingActionService(ctx, timeout=300.0)


@pytest.mark.asyncio
async def test_drain_step_barrier_integration_with_pending_service() -> None:
    """Background clear + pending service must satisfy the step barrier."""
    svc = _make_pending_service()
    action = SimpleNamespace(id=42)
    svc.set(cast(Any, action))

    async def _delayed_clear() -> None:
        await asyncio.sleep(0.05)
        svc.clear_for_action(cast(Any, action))

    run_or_schedule(_delayed_clear())

    drained = await drain_step_barrier(
        has_outstanding=svc.has_outstanding,
        timeout=2.0,
        poll_interval=0.02,
    )
    assert drained is True
    assert svc.has_outstanding() is False


@pytest.mark.asyncio
async def test_orchestrator_drain_step_barrier_delegates_to_pending_service() -> None:
    """_drain_step_barrier on the mixin must honor outstanding pending rows."""
    stub = _DrainStub()
    svc = _make_pending_service()
    stub.services = MagicMock()
    stub.services.pending_action = svc
    svc.set(cast(Any, SimpleNamespace(id=7)))

    async def _clear() -> None:
        await asyncio.sleep(0.03)
        svc.clear_primary()

    run_or_schedule(_clear())

    drained = await stub._drain_step_barrier(timeout=2.0)
    assert drained is True
    assert svc.has_outstanding() is False


def test_persistence_health_recovers_after_transient_failures() -> None:
    """A successful write after failures must reset persistence_health to ok."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_store = LocalFileStore(tmpdir)
        stream = EventStream('recover-session', file_store, worker_count=0)
        try:
            original = stream._persist.persist_event
            attempts = {'n': 0}

            def _flaky(*args, **kwargs):
                attempts['n'] += 1
                if attempts['n'] <= 1:
                    raise OSError('transient')
                return original(*args, **kwargs)

            stream._persist.persist_event = _flaky  # type: ignore[method-assign]
            stream.add_event(NullObservation(content='a'), EventSource.AGENT)
            assert stream.persistence_health == 'degraded'

            stream.add_event(NullObservation(content='b'), EventSource.AGENT)
            assert stream.persistence_health == 'ok'
            assert stream._persist_failure_streak == 0
        finally:
            stream.close()


def test_persistence_degraded_warning_emitted_once_per_health_level() -> None:
    """Degraded persistence must surface one StatusObservation per health level."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_store = LocalFileStore(tmpdir)
        stream = EventStream('warn-session', file_store, worker_count=0)
        try:
            stream._persistence_health = 'degraded'
            stub = _DrainStub()
            stub.event_stream = stream
            stub.state = MagicMock()
            stub.state.extra_data = {}

            stub._maybe_emit_persistence_degraded_warning()
            events = stream.get_matching_events()
            status_events = [e for e in events if isinstance(e, StatusObservation)]
            assert len(status_events) == 1
            assert status_events[0].status_type == 'persistence_degraded'
            assert status_events[0].extras.get('persistence_health') == 'degraded'

            stub._maybe_emit_persistence_degraded_warning()
            events_after = stream.get_matching_events()
            status_after = [e for e in events_after if isinstance(e, StatusObservation)]
            assert len(status_after) == 1

            stream._persistence_health = 'failed'
            stub._maybe_emit_persistence_degraded_warning()
            status_final = [
                e
                for e in stream.get_matching_events()
                if isinstance(e, StatusObservation)
            ]
            assert len(status_final) == 2
            assert status_final[-1].extras.get('persistence_health') == 'failed'
        finally:
            stream.close()


def test_parallel_pending_siblings_survive_partial_clear() -> None:
    """Simulated parallel batch: clearing one action must not remove siblings."""
    svc = _make_pending_service()
    a1 = SimpleNamespace(id=10)
    a2 = SimpleNamespace(id=20)
    a3 = SimpleNamespace(id=30)
    for action in (a1, a2, a3):
        svc.set(cast(Any, action))

    svc.clear_for_action(cast(Any, a2))

    assert svc.peek_for_cause(10) is a1
    assert svc.peek_for_cause(20) is None
    assert svc.peek_for_cause(30) is a3
    assert svc.has_outstanding() is True

    svc.pop_for_cause(10)
    svc.pop_for_cause(30)
    assert svc.has_outstanding() is False


def test_health_snapshot_reports_persistence_health_from_real_stream() -> None:
    """collect_orchestration_health must read persistence_health from EventStream."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_store = LocalFileStore(tmpdir)
        stream = EventStream('health-session', file_store, worker_count=0)
        try:
            stream._persistence_health = 'degraded'
            ctrl = MagicMock()
            ctrl.sid = 'health-session'
            ctrl.event_stream = stream
            ctrl.state = MagicMock()
            ctrl.state.agent_state.value = 'running'
            ctrl.state.iteration_flag.current_value = 1
            ctrl.state.iteration_flag.max_value = 100
            ctrl.state.budget_flag = None
            ctrl.state.metrics.accumulated_cost = 0.0
            ctrl.circuit_breaker_service = None
            ctrl.retry_service = MagicMock(pending_retry=False)

            snap = collect_orchestration_health(ctrl)
            assert snap['persistence_health'] == 'degraded'
            assert 'persistence_degraded' in snap['warnings']
        finally:
            stream.close()
