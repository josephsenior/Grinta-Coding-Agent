"""Tests for backend/engines/orchestrator/tools/health_check.py."""

import pytest
from unittest.mock import patch

from backend.engines.orchestrator.tools.health_check import (
    check_ultimate_editor_dependencies,
    check_atomic_refactor_dependencies,
    run_production_health_check,
)


class TestCheckUltimateEditorDependencies:
    """Test check_ultimate_editor_dependencies()."""

    def test_returns_tuple_of_bool_and_str(self):
        """Test that the function returns expected types."""
        success, message = check_ultimate_editor_dependencies()

        assert isinstance(success, bool)
        assert isinstance(message, str)
        assert len(message) > 0

    def test_message_content_indicates_status(self):
        """Test that message reflects success or failure status."""
        success, message = check_ultimate_editor_dependencies()

        if success:
            # Success message should mention operational status or readiness
            assert ("operational" in message.lower() or
                    "READY" in message or
                    "PASS" in message.upper())
        else:
            # Failure message should mention dependencies or errors
            assert ("dependencies" in message.lower() or
                    "missing" in message.lower() or
                    "failed" in message.lower())


class TestCheckAtomicRefactorDependencies:
    """Test check_atomic_refactor_dependencies()."""

    def test_returns_tuple_of_bool_and_str(self):
        """Test that the function returns expected types."""
        success, message = check_atomic_refactor_dependencies()

        assert isinstance(success, bool)
        assert isinstance(message, str)
        assert len(message) > 0

    def test_success_when_available(self):
        """Test successful check when AtomicRefactor is available."""
        success, message = check_atomic_refactor_dependencies()

        # AtomicRefactor should be available in backend
        assert success is True
        assert "operational" in message.lower() or "READY" in message


class TestRunProductionHealthCheck:
    """Test run_production_health_check()."""

    def test_all_checks_pass(self):
        """Test health check when all dependencies are satisfied."""
        with patch("backend.engines.orchestrator.tools.health_check.check_ultimate_editor_dependencies", return_value=(True, "UE OK")):
            with patch("backend.engines.orchestrator.tools.health_check.check_atomic_refactor_dependencies", return_value=(True, "AR OK")):
                result = run_production_health_check(raise_on_failure=False)

        assert result["overall_status"] == "HEALTHY"
        assert result["ultimate_editor"]["status"] == "PASS"
        assert result["ultimate_editor"]["message"] == "UE OK"
        assert result["ultimate_editor"]["critical"] is True
        assert result["atomic_refactor"]["status"] == "PASS"
        assert result["atomic_refactor"]["message"] == "AR OK"
        assert result["atomic_refactor"]["critical"] is False

    def test_non_critical_component_failure(self):
        """Test health check when only non-critical component fails."""
        with patch("backend.engines.orchestrator.tools.health_check.check_ultimate_editor_dependencies", return_value=(True, "UE OK")):
            with patch("backend.engines.orchestrator.tools.health_check.check_atomic_refactor_dependencies", return_value=(False, "AR failed")):
                result = run_production_health_check(raise_on_failure=False)

        # Should still be healthy since atomic refactor is not critical
        assert result["overall_status"] == "HEALTHY"
        assert result["ultimate_editor"]["status"] == "PASS"
        assert result["atomic_refactor"]["status"] == "FAIL"
        assert result["atomic_refactor"]["critical"] is False

    def test_critical_component_failure(self):
        """Test health check when critical component fails."""
        with patch("backend.engines.orchestrator.tools.health_check.check_ultimate_editor_dependencies", return_value=(False, "UE failed")):
            with patch("backend.engines.orchestrator.tools.health_check.check_atomic_refactor_dependencies", return_value=(True, "AR OK")):
                result = run_production_health_check(raise_on_failure=False)

        assert result["overall_status"] == "CRITICAL_FAILURE"
        assert result["ultimate_editor"]["status"] == "FAIL"
        assert result["ultimate_editor"]["message"] == "UE failed"

    def test_critical_failure_raises_with_flag(self):
        """Test that critical failure raises RuntimeError when raise_on_failure=True."""
        with patch("backend.engines.orchestrator.tools.health_check.check_ultimate_editor_dependencies", return_value=(False, "UE failed")):
            with patch("backend.engines.orchestrator.tools.health_check.check_atomic_refactor_dependencies", return_value=(True, "AR OK")):
                with pytest.raises(RuntimeError, match="health check failed"):
                    run_production_health_check(raise_on_failure=True)

    def test_critical_failure_no_raise_when_disabled(self):
        """Test critical failure returns result when raise_on_failure=False."""
        with patch("backend.engines.orchestrator.tools.health_check.check_ultimate_editor_dependencies", return_value=(False, "UE failed")):
            with patch("backend.engines.orchestrator.tools.health_check.check_atomic_refactor_dependencies", return_value=(True, "AR OK")):
                result = run_production_health_check(raise_on_failure=False)

        # Should return result without raising
        assert result["overall_status"] == "CRITICAL_FAILURE"

    def test_all_components_fail(self):
        """Test health check when all components fail."""
        with patch("backend.engines.orchestrator.tools.health_check.check_ultimate_editor_dependencies", return_value=(False, "UE failed")):
            with patch("backend.engines.orchestrator.tools.health_check.check_atomic_refactor_dependencies", return_value=(False, "AR failed")):
                result = run_production_health_check(raise_on_failure=False)

        assert result["overall_status"] == "CRITICAL_FAILURE"
        assert result["ultimate_editor"]["status"] == "FAIL"
        assert result["atomic_refactor"]["status"] == "FAIL"

    def test_result_structure_complete(self):
        """Test that result has complete expected structure."""
        with patch("backend.engines.orchestrator.tools.health_check.check_ultimate_editor_dependencies", return_value=(True, "OK")):
            with patch("backend.engines.orchestrator.tools.health_check.check_atomic_refactor_dependencies", return_value=(True, "OK")):
                result = run_production_health_check(raise_on_failure=False)

        # Check all required keys exist
        assert "overall_status" in result
        assert "ultimate_editor" in result
        assert "atomic_refactor" in result

        # Check component structure
        for component_key in ["ultimate_editor", "atomic_refactor"]:
            component = result[component_key]
            assert isinstance(component, dict)
            assert "status" in component
            assert "message" in component
            assert "critical" in component
            assert component["status"] in ["PASS", "FAIL"]
            assert isinstance(component["critical"], bool)

    def test_overall_status_values(self):
        """Test that overall_status has expected values."""
        # Test HEALTHY
        with patch("backend.engines.orchestrator.tools.health_check.check_ultimate_editor_dependencies", return_value=(True, "OK")):
            with patch("backend.engines.orchestrator.tools.health_check.check_atomic_refactor_dependencies", return_value=(True, "OK")):
                result = run_production_health_check(raise_on_failure=False)
                assert result["overall_status"] == "HEALTHY"

        # Test CRITICAL_FAILURE
        with patch("backend.engines.orchestrator.tools.health_check.check_ultimate_editor_dependencies", return_value=(False, "FAIL")):
            with patch("backend.engines.orchestrator.tools.health_check.check_atomic_refactor_dependencies", return_value=(True, "OK")):
                result = run_production_health_check(raise_on_failure=False)
                assert result["overall_status"] == "CRITICAL_FAILURE"
