"""Tests for backend.runtime.utils.process_manager — ProcessManager + metrics."""

from __future__ import annotations

import time

import pytest

from backend.runtime.utils.process_manager import (
    ManagedProcess,
    ProcessManager,
    _ProcessManagerMetrics,
    _generate_pm_recommendations,
    _generate_pm_warnings,
    _assess_pm_severity,
    get_process_manager_health_snapshot,
    get_process_manager_metrics_snapshot,
)


# ===================================================================
# ProcessManager._extract_process_name
# ===================================================================

class TestExtractProcessName:

    def setup_method(self):
        self.mgr = ProcessManager()

    def test_python(self):
        assert self.mgr._extract_process_name("python manage.py runserver") == "python"

    def test_python3(self):
        assert self.mgr._extract_process_name("python3 -m http.server") == "python3"

    def test_npm(self):
        assert self.mgr._extract_process_name("npm run dev") == "npm"

    def test_pnpm(self):
        assert self.mgr._extract_process_name("pnpm dev") == "pnpm"

    def test_node(self):
        assert self.mgr._extract_process_name("node server.js") == "node"

    def test_yarn(self):
        assert self.mgr._extract_process_name("yarn start") == "yarn"

    def test_unknown_defaults_to_first_word(self):
        assert self.mgr._extract_process_name("cargo build") == "cargo"

    def test_empty_command(self):
        assert self.mgr._extract_process_name("") == "unknown"


# ===================================================================
# ProcessManager.register/unregister/count
# ===================================================================

class TestProcessManagerRegistration:

    def test_register_process(self):
        mgr = ProcessManager()
        mgr.register_process("npm run dev", "cmd-1")
        assert mgr.count() == 1
        procs = mgr.get_running_processes()
        assert len(procs) == 1
        assert procs[0].command == "npm run dev"
        assert procs[0].process_name == "npm"
        assert procs[0].command_id == "cmd-1"

    def test_unregister_process(self):
        mgr = ProcessManager()
        mgr.register_process("node server.js", "cmd-2")
        mgr.unregister_process("cmd-2")
        assert mgr.count() == 0

    def test_unregister_nonexistent(self):
        mgr = ProcessManager()
        # Should not raise
        mgr.unregister_process("nonexistent")

    def test_multiple_processes(self):
        mgr = ProcessManager()
        mgr.register_process("npm run dev", "c1")
        mgr.register_process("python app.py", "c2")
        assert mgr.count() == 2


# ===================================================================
# ProcessManager.cleanup_all
# ===================================================================

class TestProcessManagerCleanup:

    @pytest.mark.asyncio
    async def test_cleanup_empty(self):
        mgr = ProcessManager()
        results = await mgr.cleanup_all(runtime=None)
        assert results == {}

    @pytest.mark.asyncio
    async def test_cleanup_without_runtime(self):
        mgr = ProcessManager()
        mgr.register_process("npm run dev", "c1")
        results = await mgr.cleanup_all(runtime=None)
        # Even without runtime, entries are cleared
        assert "c1" in results
        assert mgr.count() == 0


# ===================================================================
# _ProcessManagerMetrics
# ===================================================================

class TestProcessManagerMetrics:

    def test_initial_snapshot(self):
        m = _ProcessManagerMetrics()
        m._init_if_needed()
        snap = m.snapshot()
        assert snap["registered_total"] == 0
        assert snap["active_processes"] == 0

    def test_register_increments(self):
        m = _ProcessManagerMetrics()
        m.on_register()
        m.on_register()
        snap = m.snapshot()
        assert snap["registered_total"] == 2
        assert snap["active_processes"] == 2

    def test_natural_termination(self):
        m = _ProcessManagerMetrics()
        m.on_register()
        m.on_natural_termination(5.0)
        snap = m.snapshot()
        assert snap["natural_terminations_total"] == 1
        assert snap["active_processes"] == 0
        assert snap["lifetime_ms_sum"] == 5000.0
        assert snap["lifetime_ms_count"] == 1

    def test_cleanup_result_success(self):
        m = _ProcessManagerMetrics()
        m.on_register()
        m.on_cleanup_result(success=True, lifetime_sec=2.0)
        snap = m.snapshot()
        assert snap["cleanup_successes_total"] == 1
        assert snap["active_processes"] == 0

    def test_cleanup_result_failure(self):
        m = _ProcessManagerMetrics()
        m.on_register()
        m.on_cleanup_result(success=False, lifetime_sec=1.0)
        snap = m.snapshot()
        assert snap["cleanup_failures_total"] == 1

    def test_forced_kill_attempt(self):
        m = _ProcessManagerMetrics()
        m.on_forced_kill_attempt()
        snap = m.snapshot()
        assert snap["forced_kill_attempts_total"] == 1

    def test_health_snapshot(self):
        m = _ProcessManagerMetrics()
        m.on_register()
        m.on_natural_termination(4.0)
        health = m.health_snapshot()
        assert health["avg_lifetime_ms"] == 4000.0
        assert health["lifetime_samples"] == 1


# ===================================================================
# Warning/severity/recommendation helpers
# ===================================================================

class TestDiagnosticHelpers:

    def test_generate_warnings_high_active(self):
        metrics = {
            "active_processes": 10,
            "forced_kill_attempts_total": 0,
        }
        warnings = _generate_pm_warnings(metrics, [])
        assert "high_active_process_count" in warnings
        assert "active_processes_without_details" in warnings

    def test_severity_red_on_failures(self):
        metrics = {"cleanup_failures_total": 1}
        assert _assess_pm_severity(metrics, []) == "red"

    def test_severity_yellow_on_force_kill(self):
        metrics = {"cleanup_failures_total": 0}
        warnings = ["forced_kill_attempts_detected"]
        assert _assess_pm_severity(metrics, warnings) == "yellow"

    def test_severity_green_normal(self):
        metrics = {"cleanup_failures_total": 0}
        assert _assess_pm_severity(metrics, []) == "green"

    def test_recommendations(self):
        metrics = {"cleanup_failures_total": 1}
        warnings = ["active_processes_without_details", "high_active_process_count", "forced_kill_attempts_detected"]
        recs = _generate_pm_recommendations(metrics, warnings)
        assert len(recs) == 4  # One per condition


# ===================================================================
# Module-level helpers
# ===================================================================

class TestModuleLevelHelpers:

    def test_get_metrics_snapshot(self):
        snap = get_process_manager_metrics_snapshot()
        assert "registered_total" in snap

    def test_get_health_snapshot_no_processes(self):
        health = get_process_manager_health_snapshot()
        assert "metrics" in health
        assert "severity" in health
        assert "timestamp" in health

    def test_get_health_snapshot_with_processes(self):
        proc = ManagedProcess(
            command="npm run dev",
            process_name="npm",
            started_at=time.time() - 10,
            command_id="c-test",
        )
        health = get_process_manager_health_snapshot(active_processes=[proc])
        assert len(health["tracked_processes"]) == 1
        assert health["tracked_processes"][0]["command_id"] == "c-test"
        assert health["tracked_processes"][0]["lifetime_sec"] >= 0
