"""Tests for observation masking compaction."""

from __future__ import annotations

from backend.context.compactor.strategies.observation_masking_compactor import (
    ObservationMaskingCompactor,
)
from backend.context.view import View
from backend.ledger.observation import CmdOutputObservation, Observation
from backend.ledger.observation.agent import AgentCondensationObservation


async def test_masked_observations_are_not_condensation_observations() -> None:
    compactor = ObservationMaskingCompactor(attention_window=1)
    old_observation = CmdOutputObservation('old output', command='pytest')
    recent_observation = CmdOutputObservation('recent output', command='pytest')

    result = await compactor.compact(
        View(events=[old_observation, recent_observation])
    )

    assert isinstance(result, View)
    masked = result.events[0]
    assert isinstance(masked, Observation)
    assert not isinstance(masked, AgentCondensationObservation)
    assert masked.content == '<MASKED>'
    assert result.events[1] is recent_observation
