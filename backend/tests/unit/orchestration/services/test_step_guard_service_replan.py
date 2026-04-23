from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from backend.orchestration.services.step_guard_service import StepGuardService


def _make_controller(stuck: bool) -> SimpleNamespace:
    state = SimpleNamespace(extra_data={}, turn_signals=SimpleNamespace(repetition_score=0))
    state.set_extra = MagicMock()
    state.set_planning_directive = MagicMock()
    return SimpleNamespace(
        state=state,
        circuit_breaker_service=None,
        stuck_service=SimpleNamespace(
            compute_repetition_score=lambda: 0.9,
            is_stuck=lambda: stuck,
        ),
        services=SimpleNamespace(pending_action=SimpleNamespace(get=lambda: None)),
        event_stream=SimpleNamespace(add_event=MagicMock()),
        agent=SimpleNamespace(clear_queued_actions=MagicMock()),
    )


@pytest.mark.asyncio
async def test_stuck_detection_forces_one_replan_turn() -> None:
    controller = _make_controller(stuck=True)
    context = SimpleNamespace(
        get_controller=lambda: controller,
        agent_config=SimpleNamespace(warning_first_trip_enabled=False),
    )
    service = StepGuardService(cast(Any, context))

    assert await service.ensure_can_step() is False
    # Next turn consumes the replan latch and allows execution.
    assert await service.ensure_can_step() is True


@pytest.mark.asyncio
async def test_non_stuck_path_allows_step() -> None:
    controller = _make_controller(stuck=False)
    context = SimpleNamespace(
        get_controller=lambda: controller,
        agent_config=SimpleNamespace(warning_first_trip_enabled=False),
    )
    service = StepGuardService(cast(Any, context))

    assert await service.ensure_can_step() is True
