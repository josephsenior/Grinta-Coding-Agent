"""Shared pytest fixtures for SessionOrchestrator unit tests."""

import pytest

from backend.tests.unit.orchestration._session_orchestrator_helpers import (
    _make_controller,
)


@pytest.fixture
def ctrl():
    """SessionOrchestrator with fully mocked internals."""
    return _make_controller()
