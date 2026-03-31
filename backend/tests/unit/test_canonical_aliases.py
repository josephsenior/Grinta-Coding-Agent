"""Tests that legacy compatibility aliases are no longer exported."""

from __future__ import annotations

import backend.core.config as config_pkg
import backend.core.rollback as rollback_pkg
import backend.gateway.session as session_pkg
import backend.ledger as ledger_pkg
import backend.ledger.action as action_pkg
import backend.ledger.observation as observation_pkg
import backend.orchestration.services as services_pkg
import pytest


@pytest.mark.parametrize(
    ("module", "name"),
    [
        (config_pkg, "TranscriptConfig"),
        (rollback_pkg, "Snapshot"),
        (session_pkg, "Run"),
        (ledger_pkg, "Ledger"),
        (ledger_pkg, "LedgerStore"),
        (ledger_pkg, "Record"),
        (ledger_pkg, "Outcome"),
        (action_pkg, "Operation"),
        (observation_pkg, "Outcome"),
        (services_pkg, "ExecutionPolicyService"),
        (services_pkg, "OpenOperationService"),
    ],
)
def test_legacy_alias_is_not_exported(module, name: str) -> None:
    assert not hasattr(module, name)