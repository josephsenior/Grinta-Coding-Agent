"""Tests for backend.core.config.permissions_config — PermissionsConfig and related models."""

import pytest

from backend.core.config.permissions_config import (
    PermissionCategory,
    PermissionRule,
    PermissionsConfig,
    RiskLevel,
)


# ── Enums ────────────────────────────────────────────────────────────

class TestRiskLevel:
    def test_values(self):
        assert RiskLevel.LOW == "low"
        assert RiskLevel.MEDIUM == "medium"
        assert RiskLevel.HIGH == "high"
        assert RiskLevel.CRITICAL == "critical"


class TestPermissionCategory:
    def test_all_categories(self):
        cats = {c.value for c in PermissionCategory}
        assert "file_read" in cats
        assert "file_write" in cats
        assert "file_delete" in cats
        assert "network" in cats
        assert "git" in cats
        assert "package" in cats
        assert "shell" in cats
        assert "system" in cats
        assert "browser" in cats


# ── PermissionRule ───────────────────────────────────────────────────

class TestPermissionRule:
    def test_defaults(self):
        rule = PermissionRule(
            category=PermissionCategory.FILE_READ,
            risk_level=RiskLevel.LOW,
        )
        assert rule.requires_confirmation is False
        assert rule.enabled is True
        assert rule.max_per_session is None
        assert rule.blocked_patterns == []
        assert rule.allowed_patterns == []

    def test_custom_values(self):
        rule = PermissionRule(
            category=PermissionCategory.SHELL,
            risk_level=RiskLevel.HIGH,
            requires_confirmation=True,
            enabled=False,
            max_per_session=10,
            blocked_patterns=["rm -rf"],
            allowed_patterns=["ls"],
        )
        assert rule.requires_confirmation is True
        assert rule.enabled is False
        assert rule.max_per_session == 10


# ── PermissionsConfig defaults ───────────────────────────────────────

class TestPermissionsConfigDefaults:
    def test_default_values(self):
        config = PermissionsConfig()
        assert config.autonomy_level == "balanced"
        assert config.file_operations_enabled is True
        assert config.git_enabled is True
        assert config.git_allow_force_push is False
        assert config.shell_allow_sudo is False
        assert config.system_operations_enabled is False
        assert config.browser_enabled is True


# ── Presets ──────────────────────────────────────────────────────────

class TestPresets:
    def test_supervised_preset(self):
        config = PermissionsConfig.get_preset("supervised")
        assert config.autonomy_level == "supervised"
        assert config.git_allow_force_push is False
        assert config.git_allow_branch_delete is False
        assert config.shell_allow_sudo is False
        assert config.system_operations_enabled is False
        assert config.max_cost_per_task == 5.0
        assert config.warn_at_cost == 3.0

    def test_balanced_preset(self):
        config = PermissionsConfig.get_preset("balanced")
        assert config.autonomy_level == "balanced"
        assert config.max_cost_per_task == 10.0
        assert config.warn_at_cost == 7.0

    def test_full_preset(self):
        config = PermissionsConfig.get_preset("full")
        assert config.autonomy_level == "full"
        assert config.git_allow_branch_delete is True
        assert config.git_allow_force_push is False  # Still denied for safety
        assert config.shell_allow_sudo is False
        assert config.max_cost_per_task is None
        assert config.warn_at_cost == 15.0


# ── check_permission ─────────────────────────────────────────────────

class TestCheckPermission:
    def test_allowed_file_read(self):
        config = PermissionsConfig()
        allowed, reason = config.check_permission(PermissionCategory.FILE_READ, "read")
        assert allowed is True
        assert reason is None

    def test_denied_file_read(self):
        config = PermissionsConfig(file_read_enabled=False)
        allowed, reason = config.check_permission(PermissionCategory.FILE_READ, "read")
        assert allowed is False
        assert "disabled" in reason.lower()

    def test_denied_file_write(self):
        config = PermissionsConfig(file_write_enabled=False)
        allowed, reason = config.check_permission(PermissionCategory.FILE_WRITE, "write")
        assert allowed is False

    def test_denied_file_delete(self):
        config = PermissionsConfig(file_delete_enabled=False)
        allowed, reason = config.check_permission(PermissionCategory.FILE_DELETE, "delete")
        assert allowed is False

    def test_denied_git(self):
        config = PermissionsConfig(git_enabled=False)
        allowed, reason = config.check_permission(PermissionCategory.GIT, "commit")
        assert allowed is False

    def test_denied_network(self):
        config = PermissionsConfig(network_enabled=False)
        allowed, reason = config.check_permission(PermissionCategory.NETWORK, "fetch")
        assert allowed is False

    def test_denied_shell(self):
        config = PermissionsConfig(shell_enabled=False)
        allowed, reason = config.check_permission(PermissionCategory.SHELL, "exec")
        assert allowed is False

    def test_denied_browser(self):
        config = PermissionsConfig(browser_enabled=False)
        allowed, reason = config.check_permission(PermissionCategory.BROWSER, "browse")
        assert allowed is False

    def test_denied_system(self):
        config = PermissionsConfig(system_operations_enabled=False)
        allowed, reason = config.check_permission(PermissionCategory.SYSTEM, "reboot")
        assert allowed is False

    def test_denied_force_push_operation(self):
        config = PermissionsConfig(git_allow_force_push=False)
        allowed, reason = config.check_permission(PermissionCategory.GIT, "git_force_push")
        assert allowed is False
        assert "force push" in reason.lower()

    def test_denied_branch_delete_operation(self):
        config = PermissionsConfig(git_allow_branch_delete=False)
        allowed, reason = config.check_permission(PermissionCategory.GIT, "git_branch_delete")
        assert allowed is False

    def test_denied_sudo_operation(self):
        config = PermissionsConfig(shell_allow_sudo=False)
        allowed, reason = config.check_permission(PermissionCategory.SHELL, "sudo_command")
        assert allowed is False
        assert "sudo" in reason.lower()

    def test_allowed_force_push_when_enabled(self):
        config = PermissionsConfig(git_allow_force_push=True)
        allowed, reason = config.check_permission(PermissionCategory.GIT, "git_force_push")
        assert allowed is True
        assert reason is None

    def test_unknown_operation_allowed(self):
        config = PermissionsConfig()
        allowed, reason = config.check_permission(PermissionCategory.GIT, "unknown_op")
        assert allowed is True
        assert reason is None
