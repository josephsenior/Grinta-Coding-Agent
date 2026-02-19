"""Trajectory regression harness.

This harness validates recorded Forge trajectories to catch reliability drift
between releases. It is opt-in and runs only when
`FORGE_TRAJECTORY_REGRESSION_DIR` points to a directory containing JSON
trajectory files.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest


def _get_regression_dir() -> Path | None:
    raw = os.getenv("FORGE_TRAJECTORY_REGRESSION_DIR", "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.exists() or not path.is_dir():
        return None
    return path


def _iter_json_files(path: Path) -> list[Path]:
    files = sorted(path.rglob("*.json"))
    return [f for f in files if f.is_file()]


def _extract_events(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("events", "history", "trajectory"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _collect_agent_states(obj: Any, out: list[str]) -> None:
    if isinstance(obj, dict):
        state = obj.get("agent_state")
        if isinstance(state, str):
            out.append(state.lower())
        for value in obj.values():
            _collect_agent_states(value, out)
        return
    if isinstance(obj, list):
        for item in obj:
            _collect_agent_states(item, out)


def _contains_error_markers(payload: Any) -> bool:
    text = json.dumps(payload, ensure_ascii=False).lower()
    markers = (
        "circuit breaker tripped",
        "action verification failed",
        "task_validation_failed",
    )
    return any(marker in text for marker in markers)


def pytest_generate_tests(metafunc):
    if "trajectory_file" not in metafunc.fixturenames:
        return

    base = _get_regression_dir()
    if base is None:
        metafunc.parametrize("trajectory_file", [])
        return

    files = _iter_json_files(base)
    metafunc.parametrize("trajectory_file", files, ids=[f.name for f in files])


@pytest.mark.integration
def test_trajectory_regression(trajectory_file: Path) -> None:
    """Validate a recorded trajectory against baseline reliability checks."""
    with trajectory_file.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)

    events = _extract_events(payload)
    assert events, f"Trajectory has no events: {trajectory_file}"

    states: list[str] = []
    _collect_agent_states(payload, states)
    if states:
        assert states[-1] != "error", (
            f"Trajectory ended in ERROR state: {trajectory_file} "
            f"(states tail={states[-5:]})"
        )

    assert not _contains_error_markers(payload), (
        f"Reliability error marker detected in trajectory: {trajectory_file}"
    )
