"""Tests for backend.execution.security_enforcement module.

Targets the 17.4% (38 missed lines) coverage gap.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from backend.execution.security_enforcement import SecurityEnforcementMixin


class _FakeRuntime(SecurityEnforcementMixin):
    """Concrete host for the mixin."""

    def __init__(
        self,
        analyzer=None,
        enforce=False,
        block_high=False,
        *,
        execution_profile='standard',
        allow_network=False,
        allow_package_installs=False,
        allow_background=False,
        allow_sensitive_path=False,
        workspace_root=None,
        git_allowlist=None,
        package_allowlist=None,
        network_allowlist=None,
    ):
        self.security_analyzer = analyzer
        self.config = MagicMock()
        self.config.security.enforce_security = enforce
        self.config.security.block_high_risk = block_high
        self.config.security.execution_profile = execution_profile
        self.config.security.allow_network_commands = allow_network
        self.config.security.allow_package_installs = allow_package_installs
        self.config.security.allow_background_processes = allow_background
        self.config.security.allow_sensitive_path_access = allow_sensitive_path
        self.config.security.hardened_local_git_allowlist = list(
            git_allowlist
            or ['status', 'diff', 'log', 'show', 'branch', 'rev-parse', 'ls-files']
        )
        self.config.security.hardened_local_package_allowlist = list(
            package_allowlist or []
        )
        self.config.security.hardened_local_network_allowlist = list(
            network_allowlist or []
        )
        self.workspace_root = Path(workspace_root or Path.cwd())


# ------------------------------------------------------------------
# _check_action_confirmation
# ------------------------------------------------------------------
class TestCheckActionConfirmation:
    def test_no_confirmation_state(self):
        rt = _FakeRuntime()
        action = MagicMock(spec=[])  # no confirmation_state attr
        assert rt._check_action_confirmation(action) is None

    def test_awaiting_confirmation_non_file_edit(self):
        from backend.ledger.action import ActionConfirmationStatus

        rt = _FakeRuntime()
        action = MagicMock()
        action.confirmation_state = ActionConfirmationStatus.AWAITING_CONFIRMATION
        result = rt._check_action_confirmation(action)
        # Non-FileEditAction should return NullObservation
        assert result is not None
        assert result.__class__.__name__ == 'NullObservation'

    def test_awaiting_confirmation_file_edit_allowed(self):
        from backend.ledger.action import ActionConfirmationStatus, FileEditAction

        rt = _FakeRuntime()
        action = MagicMock(spec=FileEditAction)
        action.confirmation_state = ActionConfirmationStatus.AWAITING_CONFIRMATION
        result = rt._check_action_confirmation(action)
        # FileEditAction is allowed through for dry-run preview
        assert result is None

    def test_rejected_returns_user_reject(self):
        from backend.ledger.action import ActionConfirmationStatus

        rt = _FakeRuntime()
        action = MagicMock()
        action.confirmation_state = ActionConfirmationStatus.REJECTED
        result = rt._check_action_confirmation(action)
        assert result is not None
        assert result.__class__.__name__ == 'UserRejectObservation'

    def test_confirmed_returns_none(self):
        from backend.ledger.action import ActionConfirmationStatus

        rt = _FakeRuntime()
        action = MagicMock()
        action.confirmation_state = ActionConfirmationStatus.CONFIRMED
        result = rt._check_action_confirmation(action)
        assert result is None


# ------------------------------------------------------------------
# _enforce_security
# ------------------------------------------------------------------
class TestEnforceSecurity:
    def test_no_analyzer_returns_none(self):
        rt = _FakeRuntime(analyzer=None, enforce=True)
        action = MagicMock()
        result = rt._enforce_security(action)
        assert result is None

    def test_enforce_disabled_returns_none(self):
        rt = _FakeRuntime(analyzer=MagicMock(), enforce=False)
        action = MagicMock()
        result = rt._enforce_security(action)
        assert result is None

    def test_high_risk_blocked(self):
        from backend.core.enums import ActionSecurityRisk

        analyzer = MagicMock()
        analyzer.security_risk = AsyncMock(return_value=ActionSecurityRisk.HIGH)
        rt = _FakeRuntime(analyzer=analyzer, enforce=True, block_high=True)
        action = MagicMock()
        action.action = 'test_action'
        with patch('asyncio.get_running_loop', side_effect=RuntimeError):
            with patch('asyncio.run', return_value=ActionSecurityRisk.HIGH):
                result = rt._enforce_security(action)
        assert result is not None
        assert result.__class__.__name__ == 'ErrorObservation'

    def test_high_risk_requires_confirmation(self):
        from backend.core.enums import ActionSecurityRisk
        from backend.ledger.action import ActionConfirmationStatus

        analyzer = MagicMock()
        analyzer.security_risk = AsyncMock(return_value=ActionSecurityRisk.HIGH)
        rt = _FakeRuntime(analyzer=analyzer, enforce=True, block_high=False)
        action = MagicMock()
        action.action = 'test_action'
        action.confirmation_state = ActionConfirmationStatus.REJECTED  # Not CONFIRMED
        with patch('asyncio.get_running_loop', side_effect=RuntimeError):
            result = rt._enforce_security(action)
        assert result is not None
        assert result.__class__.__name__ == 'NullObservation'
        assert (
            action.confirmation_state == ActionConfirmationStatus.AWAITING_CONFIRMATION
        )

    def test_medium_risk_allowed(self):
        from backend.core.enums import ActionSecurityRisk

        analyzer = MagicMock()
        rt = _FakeRuntime(analyzer=analyzer, enforce=True, block_high=False)
        action = MagicMock()
        action.action = 'test_action'
        with patch('asyncio.get_running_loop', side_effect=RuntimeError):
            with patch('asyncio.run', return_value=ActionSecurityRisk.MEDIUM):
                result = rt._enforce_security(action)
        assert result is None

    def test_low_risk_allowed(self):
        from backend.core.enums import ActionSecurityRisk

        analyzer = MagicMock()
        rt = _FakeRuntime(analyzer=analyzer, enforce=True, block_high=False)
        action = MagicMock()
        action.action = 'test_action'
        with patch('asyncio.get_running_loop', side_effect=RuntimeError):
            with patch('asyncio.run', return_value=ActionSecurityRisk.LOW):
                result = rt._enforce_security(action)
        assert result is None

    def test_precomputed_high_risk_skips_duplicate_analyzer_call(self):
        from backend.core.enums import ActionSecurityRisk
        from backend.ledger.action import CmdRunAction

        analyzer = MagicMock()
        analyzer.security_risk = AsyncMock(side_effect=AssertionError('should not run'))
        rt = _FakeRuntime(analyzer=analyzer, enforce=True, block_high=True)
        action = CmdRunAction(command='rm -rf tmp')
        action.security_risk = ActionSecurityRisk.HIGH

        result = rt._enforce_security(action)

        assert result is not None
        assert result.__class__.__name__ == 'ErrorObservation'
        analyzer.security_risk.assert_not_called()

    def test_hardened_local_blocks_background_processes(self):
        from backend.ledger.action import CmdRunAction

        rt = _FakeRuntime(
            analyzer=None,
            enforce=True,
            execution_profile='hardened_local',
        )
        action = CmdRunAction(command='sleep 100', is_background=True)

        result = rt._enforce_security(action)

        assert result is not None
        assert result.__class__.__name__ == 'ErrorObservation'
        assert 'background processes are disabled' in result.content

    def test_sandboxed_local_reuses_hardened_local_command_policy(self):
        from backend.ledger.action import CmdRunAction

        rt = _FakeRuntime(
            analyzer=None,
            enforce=True,
            execution_profile='sandboxed_local',
        )
        action = CmdRunAction(command='curl https://example.com')

        result = rt._enforce_security(action)

        assert result is not None
        assert result.__class__.__name__ == 'ErrorObservation'
        assert 'workspace-scoped allowlist' in result.content

    def test_hardened_local_blocks_network_commands(self):
        from backend.ledger.action import CmdRunAction

        rt = _FakeRuntime(
            analyzer=None,
            enforce=True,
            execution_profile='hardened_local',
        )
        action = CmdRunAction(command='curl https://example.com')

        result = rt._enforce_security(action)

        assert result is not None
        assert result.__class__.__name__ == 'ErrorObservation'
        assert 'workspace-scoped allowlist' in result.content

    def test_hardened_local_blocks_package_installs(self):
        from backend.ledger.action import CmdRunAction

        rt = _FakeRuntime(
            analyzer=None,
            enforce=True,
            execution_profile='hardened_local',
        )
        action = CmdRunAction(command='pip install requests')

        result = rt._enforce_security(action)

        assert result is not None
        assert result.__class__.__name__ == 'ErrorObservation'
        assert 'workspace-scoped allowlist' in result.content

    def test_hardened_local_blocks_sensitive_file_reads(self):
        from backend.ledger.action import FileReadAction

        rt = _FakeRuntime(
            analyzer=None,
            enforce=True,
            execution_profile='hardened_local',
        )
        action = FileReadAction(path='.env')

        result = rt._enforce_security(action)

        assert result is not None
        assert result.__class__.__name__ == 'ErrorObservation'
        assert 'sensitive file access is disabled' in result.content

    def test_hardened_local_allows_git_subcommand_in_workspace_allowlist(self):
        from backend.ledger.action import CmdRunAction

        rt = _FakeRuntime(
            analyzer=None,
            enforce=True,
            execution_profile='hardened_local',
            workspace_root=Path.cwd(),
        )
        action = CmdRunAction(command='git diff', cwd='.')

        result = rt._enforce_security(action)

        assert result is None

    def test_hardened_local_blocks_git_subcommand_outside_workspace(self):
        from backend.ledger.action import CmdRunAction

        rt = _FakeRuntime(
            analyzer=None,
            enforce=True,
            execution_profile='hardened_local',
            workspace_root=Path.cwd(),
            git_allowlist=['status'],
        )
        action = CmdRunAction(command='git status', cwd=str(Path.cwd().parent))

        result = rt._enforce_security(action)

        assert result is not None
        assert 'must stay inside the workspace' in result.content

    def test_hardened_local_allows_package_command_from_allowlist(self):
        from backend.ledger.action import CmdRunAction

        rt = _FakeRuntime(
            analyzer=None,
            enforce=True,
            execution_profile='hardened_local',
            workspace_root=Path.cwd(),
            package_allowlist=['npm_install'],
        )
        action = CmdRunAction(command='npm install', cwd='.')

        result = rt._enforce_security(action)

        assert result is None

    def test_hardened_local_blocks_network_command_not_in_allowlist(self):
        from backend.ledger.action import CmdRunAction

        rt = _FakeRuntime(
            analyzer=None,
            enforce=True,
            execution_profile='hardened_local',
            workspace_root=Path.cwd(),
            network_allowlist=['wget'],
        )
        action = CmdRunAction(command='curl https://example.com', cwd='.')

        result = rt._enforce_security(action)

        assert result is not None
        assert 'is not in the workspace-scoped allowlist' in result.content
