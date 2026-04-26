"""Tests for backend/engine/tools/health_check.py."""

# trunk-ignore-begin(bandit)

from unittest.mock import patch

import pytest

from backend.engine.tools.health_check import (
    HealthCheckResult,
    check_atomic_refactor_dependencies,
    check_structure_editor_dependencies,
    run_production_health_check,
)


def _run_hc() -> HealthCheckResult:
    """Helper to run health check without raising."""
    return run_production_health_check(raise_on_failure=False)


class TestCheckStructureEditorDependencies:
    """Test check_structure_editor_dependencies()."""

    def test_returns_tuple_of_bool_and_str(self):
        """Test that the function returns expected types."""
        success, message = check_structure_editor_dependencies()

        assert isinstance(success, bool)
        assert isinstance(message, str)
        assert message

    def test_message_content_indicates_status(self):
        """Test that message reflects success or failure status."""
        success, message = check_structure_editor_dependencies()

        if success:
            assert (
                "operational" in message.lower()
                or "READY" in message
                or "PASS" in message.upper()
            )
        else:
            assert (
                "dependencies" in message.lower()
                or "missing" in message.lower()
                or "failed" in message.lower()
            )


class TestCheckAtomicRefactorDependencies:
    """Test check_atomic_refactor_dependencies()."""

    def test_returns_tuple_of_bool_and_str(self):
        """Test that the function returns expected types."""
        success, message = check_atomic_refactor_dependencies()

        assert isinstance(success, bool)
        assert isinstance(message, str)
        assert message

    def test_success_when_available(self):
        """Test successful check when AtomicRefactor is available."""
        success, message = check_atomic_refactor_dependencies()

        assert success is True
        assert "operational" in message.lower() or "READY" in message


class TestRunProductionHealthCheck:
    """Test run_production_health_check()."""

    def test_all_checks_pass(self):
        """Test health check when all dependencies are satisfied."""
        with patch("backend.engine.tools.health_check.check_structure_editor_dependencies", return_value=(True, "UE OK")):
            with patch("backend.engine.tools.health_check.check_atomic_refactor_dependencies", return_value=(True, "AR OK")):
                res = _run_hc()

        assert res["overall_status"] == "HEALTHY"
        # pylint: disable=unsubscriptable-object
        ue_comp = res["symbol_editor"]

        ar_comp = res["atomic_refactor"]
        assert ar_comp["status"] == "PASS"
        assert ar_comp["message"] == "AR OK"
        assert ar_comp["critical"] is False

    def test_non_critical_component_failure(self):
        """Test health check when only non-critical component fails."""
        with patch("backend.engine.tools.health_check.check_structure_editor_dependencies", return_value=(True, "UE OK")):
            with patch("backend.engine.tools.health_check.check_atomic_refactor_dependencies", return_value=(False, "AR failed")):
                res = _run_hc()

        assert res["overall_status"] == "HEALTHY"
        # pylint: disable=unsubscriptable-object
        assert res["symbol_editor"]["status"] == "PASS"
        assert res["atomic_refactor"]["status"] == "FAIL"

    def test_critical_component_failure(self):
        """Test health check when critical component fails."""
        with patch("backend.engine.tools.health_check.check_structure_editor_dependencies", return_value=(False, "UE failed")):
            with patch("backend.engine.tools.health_check.check_atomic_refactor_dependencies", return_value=(True, "AR OK")):
                res = _run_hc()

        # pylint: disable=unsubscriptable-object
        assert res["overall_status"] == "CRITICAL_FAILURE"
        assert res["symbol_editor"]["status"] == "FAIL"
        assert res["symbol_editor"]["message"] == "UE failed"

    def test_critical_failure_raises_with_flag(self):
        """Test that critical failure raises RuntimeError when raise_on_failure=True."""
        with patch("backend.engine.tools.health_check.check_structure_editor_dependencies", return_value=(False, "UE failed")):
            with patch("backend.engine.tools.health_check.check_atomic_refactor_dependencies", return_value=(True, "AR OK")):
                with pytest.raises(RuntimeError, match="health check failed"):
                    run_production_health_check(raise_on_failure=True)

    def test_critical_failure_no_raise_when_disabled(self):
        """Test critical failure returns result when raise_on_failure=False."""
        with patch("backend.engine.tools.health_check.check_structure_editor_dependencies", return_value=(False, "UE failed")):
            with patch("backend.engine.tools.health_check.check_atomic_refactor_dependencies", return_value=(True, "AR OK")):
                res = _run_hc()

        assert res["overall_status"] == "CRITICAL_FAILURE"

    def test_all_components_fail(self):
        """Test health check when all components fail."""
        with patch("backend.engine.tools.health_check.check_structure_editor_dependencies", return_value=(False, "UE failed")):
            with patch("backend.engine.tools.health_check.check_atomic_refactor_dependencies", return_value=(False, "AR failed")):
                res = _run_hc()

        # pylint: disable=unsubscriptable-object
        assert res["overall_status"] == "CRITICAL_FAILURE"
        assert res["symbol_editor"]["status"] == "FAIL"
        assert res["atomic_refactor"]["status"] == "FAIL"

    def test_result_structure_complete(self):
        """Test that res has complete expected structure."""
        with patch("backend.engine.tools.health_check.check_structure_editor_dependencies", return_value=(True, "OK")):
            with patch("backend.engine.tools.health_check.check_atomic_refactor_dependencies", return_value=(True, "OK")):
                res = _run_hc()

        assert "overall_status" in res
        assert "symbol_editor" in res
        assert "atomic_refactor" in res

        # pylint: disable=unsubscriptable-object
        ue_comp = res["symbol_editor"]
        assert isinstance(ue_comp, dict)
        assert "status" in ue_comp
        assert "message" in ue_comp

        ar_comp = res["atomic_refactor"]
        assert isinstance(ar_comp, dict)
        assert "status" in ar_comp
        assert "message" in ar_comp

    def test_overall_status_values(self):
        """Test that overall_status has expected values."""
        with patch("backend.engine.tools.health_check.check_structure_editor_dependencies", return_value=(True, "OK")):
            with patch("backend.engine.tools.health_check.check_atomic_refactor_dependencies", return_value=(True, "OK")):
                res = _run_hc()
                assert res["overall_status"] == "HEALTHY"

        with patch("backend.engine.tools.health_check.check_structure_editor_dependencies", return_value=(False, "FAIL")):
            with patch("backend.engine.tools.health_check.check_atomic_refactor_dependencies", return_value=(True, "OK")):
                res = _run_hc()
                assert res["overall_status"] == "CRITICAL_FAILURE"


# trunk-ignore-end(bandit)