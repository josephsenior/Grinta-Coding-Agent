"""Configuration schemas for App permission and capability settings."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from backend._canonical import CanonicalModelMetaclass
from backend.core.constants import (
    DEFAULT_BROWSER_MAX_PAGES,
    DEFAULT_FILE_OPERATIONS_BLOCKED_PATHS,
    DEFAULT_FILE_OPERATIONS_MAX_SIZE_MB,
    DEFAULT_GIT_PROTECTED_BRANCHES,
    DEFAULT_NETWORK_MAX_REQUESTS_PER_MINUTE,
    DEFAULT_PACKAGE_ALLOWED_MANAGERS,
    DEFAULT_SHELL_BLOCKED_COMMANDS,
    DEFAULT_SHELL_CONFIRMATION_PATTERNS,
)


class RiskLevel(str, Enum):
    """Risk levels for agent actions."""

    LOW = "low"  # Safe operations: read files, list directories
    MEDIUM = "medium"  # Moderate risk: write files, install packages
    HIGH = "high"  # Risky operations: delete files, git commits
    CRITICAL = "critical"  # Dangerous: force push, rm -rf, sudo, system modifications


class PermissionCategory(str, Enum):
    """Categories of permissions for different operation types."""

    FILE_READ = "file_read"  # Reading files and directories
    FILE_WRITE = "file_write"  # Creating/modifying files
    FILE_DELETE = "file_delete"  # Deleting files and directories
    NETWORK = "network"  # Network requests, API calls
    GIT = "git"  # Git operations
    PACKAGE = "package"  # Package installations
    SHELL = "shell"  # Shell command execution
    SYSTEM = "system"  # System-level operations
    BROWSER = "browser"  # Web browsing


class PermissionRule(BaseModel, metaclass=CanonicalModelMetaclass):
    """Individual permission rule."""

    category: PermissionCategory
    risk_level: RiskLevel
    requires_confirmation: bool = Field(default=False)
    enabled: bool = Field(default=True)
    max_per_session: int | None = Field(
        default=None, description="Maximum uses per session, None for unlimited"
    )
    blocked_patterns: list[str] = Field(
        default_factory=list, description="Regex patterns to block"
    )
    allowed_patterns: list[str] = Field(
        default_factory=list, description="Regex patterns to allow (overrides blocks)"
    )

    model_config = {"extra": "forbid"}


class PermissionsConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Fine-grained permissions configuration.

    Controls what operations the agent can perform and at what level
    of autonomy. Can be customized per autonomy level.

    Example:
        ```python
        permissions = PermissionsConfig(
            autonomy_level="balanced",
            file_operations_max_size_mb=10,
            git_allow_force_push=False,
            network_allowed_domains=["github.com", "pypi.org"]
        )
        ```

    """

    # General settings
    autonomy_level: str = Field(default="balanced")
    "Autonomy level these permissions apply to"

    # File operations
    file_operations_enabled: bool = Field(default=True)
    "Whether file operations are allowed"

    file_read_enabled: bool = Field(default=True)
    "Whether reading files is allowed"

    file_write_enabled: bool = Field(default=True)
    "Whether writing files is allowed"

    file_delete_enabled: bool = Field(default=True)
    "Whether deleting files is allowed"

    file_operations_max_size_mb: int = Field(
        default=DEFAULT_FILE_OPERATIONS_MAX_SIZE_MB
    )
    "Maximum file size for read/write operations in MB"

    file_operations_blocked_paths: list[str] = Field(
        default_factory=lambda: DEFAULT_FILE_OPERATIONS_BLOCKED_PATHS,
    )
    "Glob patterns for blocked file paths"

    # Git operations
    git_enabled: bool = Field(default=True)
    "Whether git operations are allowed"

    git_allow_commit: bool = Field(default=True)
    "Whether git commits are allowed"

    git_allow_push: bool = Field(default=True)
    "Whether git push is allowed"

    git_allow_force_push: bool = Field(default=False)
    "Whether git force push is allowed"

    git_allow_branch_delete: bool = Field(default=False)
    "Whether deleting branches is allowed"

    git_protected_branches: list[str] = Field(
        default_factory=lambda: DEFAULT_GIT_PROTECTED_BRANCHES,
    )
    "Branches that cannot be force-pushed or deleted"

    # Network operations
    network_enabled: bool = Field(default=True)
    "Whether network operations are allowed"

    network_allowed_domains: list[str] | None = Field(default=None)
    "List of allowed domains (None = all allowed)"

    network_blocked_domains: list[str] = Field(
        default_factory=list,
    )
    "List of blocked domains"

    network_max_requests_per_minute: int = Field(
        default=DEFAULT_NETWORK_MAX_REQUESTS_PER_MINUTE
    )
    "Rate limit for network requests"

    # Package management
    package_install_enabled: bool = Field(default=True)
    "Whether package installations are allowed"

    package_allowed_managers: list[str] = Field(
        default_factory=lambda: DEFAULT_PACKAGE_ALLOWED_MANAGERS,
    )
    "Allowed package managers"

    package_require_lockfile: bool = Field(default=False)
    "Whether to require lockfile for installations"

    package_blocked_packages: list[str] = Field(default_factory=list)
    "Specific packages that are blocked"

    # Shell operations
    shell_enabled: bool = Field(default=True)
    "Whether shell commands are allowed"

    shell_allow_sudo: bool = Field(default=False)
    "Whether sudo commands are allowed"

    shell_blocked_commands: list[str] = Field(
        default_factory=lambda: DEFAULT_SHELL_BLOCKED_COMMANDS,
    )
    "Shell commands/patterns that are blocked"

    shell_require_confirmation_patterns: list[str] = Field(
        default_factory=lambda: DEFAULT_SHELL_CONFIRMATION_PATTERNS,
    )
    "Command patterns that require confirmation"

    # Browser operations
    browser_enabled: bool = Field(default=True)
    "Whether browser operations are allowed"

    browser_allow_downloads: bool = Field(default=True)
    "Whether downloading files via browser is allowed"

    browser_max_pages: int = Field(default=DEFAULT_BROWSER_MAX_PAGES)
    "Maximum number of browser pages/tabs"

    # System operations
    system_operations_enabled: bool = Field(default=False)
    "Whether system-level operations are allowed"

    system_allow_process_management: bool = Field(default=False)
    "Whether managing processes is allowed"

    system_allow_service_management: bool = Field(default=False)
    "Whether managing system services is allowed"

    # Resource limits
    max_file_writes_per_task: int = Field(default=100)
    "Maximum number of file write operations per task"

    max_shell_commands_per_task: int = Field(default=200)
    "Maximum number of shell commands per task"

    max_api_calls_per_task: int = Field(default=500)
    "Maximum number of API calls per task"

    # Spending limits
    max_cost_per_task: float | None = Field(default=None)
    "Maximum cost per task in USD (None = unlimited)"

    warn_at_cost: float | None = Field(default=None)
    "Cost threshold to warn user in USD"

    model_config = {"extra": "forbid"}

    @classmethod
    def get_preset(cls, autonomy_level: str) -> PermissionsConfig:
        """Get a preset permissions configuration for an autonomy level.

        Args:
            autonomy_level: One of 'supervised', 'balanced', or 'full'

        Returns:
            PermissionsConfig configured for the specified autonomy level

        """
        if autonomy_level == "supervised":
            return cls(
                autonomy_level="supervised",
                git_allow_force_push=False,
                git_allow_branch_delete=False,
                shell_allow_sudo=False,
                system_operations_enabled=False,
                max_cost_per_task=5.0,
                warn_at_cost=3.0,
            )
        if autonomy_level == "balanced":
            return cls(
                autonomy_level="balanced",
                git_allow_force_push=False,
                git_allow_branch_delete=False,
                shell_allow_sudo=False,
                system_operations_enabled=False,
                max_cost_per_task=10.0,
                warn_at_cost=7.0,
            )
        # full
        return cls(
            autonomy_level="full",
            git_allow_force_push=False,  # Still deny by default for safety
            git_allow_branch_delete=True,
            shell_allow_sudo=False,  # Still deny sudo for safety
            system_operations_enabled=False,  # Still deny system ops
            max_cost_per_task=None,  # No limit
            warn_at_cost=15.0,
        )

    def check_permission(
        self,
        category: PermissionCategory,
        operation: str,
        **kwargs: Any,
    ) -> tuple[bool, str | None]:
        """Check if an operation is allowed.

        Args:
            category: Permission category
            operation: Specific operation being performed
            **kwargs: Additional context (file_path, command, etc.)

        Returns:
            Tuple of (is_allowed, reason_if_denied)

        """
        # Check category-level permission
        category_result = self._check_category_permission(category)
        if category_result is not None:
            return category_result

        # Check operation-specific permission
        operation_result = self._check_operation_permission(operation)
        if operation_result is not None:
            return operation_result

        return True, None

    def _check_category_permission(
        self, category: PermissionCategory
    ) -> tuple[bool, str] | None:
        """Check if a permission category is enabled.

        Args:
            category: The permission category to check

        Returns:
            (False, reason) if denied, None if category is enabled

        """
        category_checks = {
            PermissionCategory.FILE_READ: (
                self.file_read_enabled,
                "File read operations are disabled",
            ),
            PermissionCategory.FILE_WRITE: (
                self.file_write_enabled,
                "File write operations are disabled",
            ),
            PermissionCategory.FILE_DELETE: (
                self.file_delete_enabled,
                "File delete operations are disabled",
            ),
            PermissionCategory.GIT: (self.git_enabled, "Git operations are disabled"),
            PermissionCategory.NETWORK: (
                self.network_enabled,
                "Network operations are disabled",
            ),
            PermissionCategory.SHELL: (
                self.shell_enabled,
                "Shell operations are disabled",
            ),
            PermissionCategory.BROWSER: (
                self.browser_enabled,
                "Browser operations are disabled",
            ),
            PermissionCategory.SYSTEM: (
                self.system_operations_enabled,
                "System operations are disabled",
            ),
        }

        if category in category_checks:
            enabled, reason = category_checks[category]
            if not enabled:
                return False, reason

        return None

    def _check_operation_permission(self, operation: str) -> tuple[bool, str] | None:
        """Check if a specific operation is allowed.

        Args:
            operation: The operation to check

        Returns:
            (False, reason) if denied, None if operation is allowed

        """
        operation_checks = {
            "git_force_push": (self.git_allow_force_push, "Force push is not allowed"),
            "git_branch_delete": (
                self.git_allow_branch_delete,
                "Branch deletion is not allowed",
            ),
            "sudo_command": (self.shell_allow_sudo, "Sudo commands are not allowed"),
        }

        if operation in operation_checks:
            allowed, reason = operation_checks[operation]
            if not allowed:
                return False, reason

        return None
