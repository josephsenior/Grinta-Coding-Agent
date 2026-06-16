"""Tests for LLM step timeout helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.core.llm_step_timeout import resolve_step_task_liveness_seconds


def test_resolve_step_task_liveness_covers_two_astep_attempts() -> None:
    agent = MagicMock()
    agent.config.llm_step_timeout_seconds = 300.0

    liveness = resolve_step_task_liveness_seconds(
        agent,
        default_liveness_seconds=600.0,
    )

    assert liveness == (2.0 * 300.0) + 120.0
    assert liveness > 600.0


def test_resolve_step_task_liveness_unbounded_when_step_timeout_disabled() -> None:
    agent = MagicMock()
    agent.config.llm_step_timeout_seconds = 0

    assert (
        resolve_step_task_liveness_seconds(agent, default_liveness_seconds=600.0)
        == 600.0
    )
