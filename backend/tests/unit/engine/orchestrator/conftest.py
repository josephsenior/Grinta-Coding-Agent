"""Shared fixtures for orchestrator unit tests."""

from __future__ import annotations

import typing

import pytest


@pytest.fixture(autouse=True)
def _isolate_streaming_checkpoint_root(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> typing.Generator[None, None, None]:
    """Keep streaming WAL checkpoints out of the developer's APP_DATA_DIR."""
    checkpoint_root = tmp_path / 'app_data' / 'streaming_checkpoints'
    checkpoint_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv('APP_DATA_DIR', str(tmp_path / 'app_data'))
    yield
