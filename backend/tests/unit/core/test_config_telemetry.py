"""Tests for backend.core.config.config_telemetry — ConfigTelemetry counter state machine."""

from __future__ import annotations

from backend.core.config.config_telemetry import ConfigTelemetry


class TestConfigTelemetry:
    def setup_method(self):
        self.ct = ConfigTelemetry()

    # ── initial state ────────────────────────────────────────────────

    def test_initial_snapshot(self):
        snap = self.ct.snapshot()
        assert snap['schema_missing'] == 0
        assert snap['schema_mismatch'] == {}
        assert snap['invalid_agents'] == {}
        assert snap['invalid_base'] == 0

    # ── record_schema_missing ────────────────────────────────────────

    def test_schema_missing_increments(self):
        self.ct.record_schema_missing()
        self.ct.record_schema_missing()
        assert self.ct.snapshot()['schema_missing'] == 2

    # ── record_schema_mismatch ───────────────────────────────────────

    def test_schema_mismatch_counts_by_key(self):
        self.ct.record_schema_mismatch('v2')
        self.ct.record_schema_mismatch('v2')
        self.ct.record_schema_mismatch('v3')
        snap = self.ct.snapshot()
        assert snap['schema_mismatch'] == {'v2': 2, 'v3': 1}

    def test_schema_mismatch_none_becomes_unknown(self):
        self.ct.record_schema_mismatch(None)
        snap = self.ct.snapshot()
        assert snap['schema_mismatch'] == {'unknown': 1}

    # ── record_invalid_agent ─────────────────────────────────────────

    def test_invalid_agent_counts(self):
        self.ct.record_invalid_agent('agent_a')
        self.ct.record_invalid_agent('agent_b')
        self.ct.record_invalid_agent('agent_a')
        snap = self.ct.snapshot()
        assert snap['invalid_agents'] == {'agent_a': 2, 'agent_b': 1}

    # ── record_invalid_base ──────────────────────────────────────────

    def test_invalid_base_increments(self):
        self.ct.record_invalid_base()
        assert self.ct.snapshot()['invalid_base'] == 1
        self.ct.record_invalid_base()
        assert self.ct.snapshot()['invalid_base'] == 2

    # ── reset ────────────────────────────────────────────────────────

    def test_reset_clears_all(self):
        self.ct.record_schema_missing()
        self.ct.record_schema_mismatch('v2')
        self.ct.record_invalid_agent('agent_x')
        self.ct.record_invalid_base()
        self.ct.reset()
        snap = self.ct.snapshot()
        assert snap['schema_missing'] == 0
        assert snap['schema_mismatch'] == {}
        assert snap['invalid_agents'] == {}
        assert snap['invalid_base'] == 0

    # ── snapshot returns a fresh dict ────────────────────────────────

    def test_snapshot_returns_new_dict(self):
        a = self.ct.snapshot()
        b = self.ct.snapshot()
        assert a == b
        assert a is not b
