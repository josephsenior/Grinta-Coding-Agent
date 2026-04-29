"""Security enforcement mixin for Runtime action gating.

Extracts security risk evaluation and action confirmation checks from
the Runtime base class into a focused, testable mixin.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import TYPE_CHECKING, Any

from backend.core.logger import app_logger as logger
from backend.execution.editor_only_shell_policy import evaluate_editor_only_shell_block
from backend.execution.sandboxing import is_workspace_restricted_profile
from backend.security.command_analyzer import CommandAnalyzer

if TYPE_CHECKING:
    from backend.ledger.action import Action
    from backend.ledger.observation import Observation


_PACKAGE_INSTALL_RE = re.compile(
    r'\b(?:python\s+-m\s+pip\s+install|pip(?:3)?\s+install|npm\s+install|pnpm\s+add|yarn\s+add|Install-Module|Install-Package)\b',
    re.I,
)
_SENSITIVE_PATH_PARTS = (
    '.env',
    '.env.local',
    '.env.production',
    '.ssh',
    '.aws',
    '.pypirc',
    '.npmrc',
    '.git-credentials',
    '.docker',
    'id_rsa',
    'id_ed25519',
    'known_hosts',
    'credentials.json',
)
_GIT_FLAGS_WITH_VALUES = {'-c', '-C', '--git-dir', '--work-tree'}
_NETWORK_COMMAND_ALIASES = {
    'curl': 'curl',
    'wget': 'wget',
    'scp': 'scp',
    'rsync': 'rsync',
    'nc': 'netcat',
    'netcat': 'netcat',
    'invoke-webrequest': 'invoke-webrequest',
    'invoke-restmethod': 'invoke-restmethod',
    'iwr': 'invoke-webrequest',
    'irm': 'invoke-restmethod',
}
_PACKAGE_COMMAND_PATTERNS: tuple[tuple[str, str], ...] = (
    (r'\b(?:python\s+-m\s+pip|pip(?:3)?)\s+install\b', 'pip_install'),
    (r'\buv\s+(?:pip\s+install|add)\b', 'uv_install'),
    (r'\bpoetry\s+add\b', 'poetry_add'),
    (r'\bconda\s+install\b', 'conda_install'),
    (r'\bpipx\s+install\b', 'pipx_install'),
    (r'\bnpm\s+install\b', 'npm_install'),
    (r'\bpnpm\s+add\b', 'pnpm_add'),
    (r'\byarn\s+add\b', 'yarn_add'),
    (r'\binstall-module\b', 'install_module'),
    (r'\binstall-package\b', 'install_package'),
)


@dataclass(slots=True)
class SecurityPolicyDecision:
    """Runtime security-policy decision for a single action."""

    risk: Any | None = None
    block_message: str | None = None
    require_confirmation: bool = False


def normalize_allowlist(values: Any) -> set[str]:
    return {
        str(value).strip().lower() for value in (values or ()) if str(value).strip()
    }


def tokenize_command(command: str) -> list[str]:
    if not command.strip():
        return []
    try:
        return shlex.split(command, posix=False)
    except ValueError:
        return command.strip().split()


def extract_git_subcommand(command: str) -> str | None:
    tokens = tokenize_command(command)
    if not tokens or tokens[0].lower() != 'git':
        return None

    skip_next = False
    for token in tokens[1:]:
        if skip_next:
            skip_next = False
            continue
        if token in _GIT_FLAGS_WITH_VALUES:
            skip_next = True
            continue
        if token.startswith('-'):
            continue
        return token.strip().lower()
    return None


def classify_package_command(command: str) -> str | None:
    lowered = command.lower()
    for pattern, label in _PACKAGE_COMMAND_PATTERNS:
        if re.search(pattern, lowered):
            return label
    return None


def classify_network_command(command: str, is_network_operation: bool) -> str | None:
    tokens = tokenize_command(command)
    if not tokens:
        return None
    normalized = tokens[0].strip().lower()
    if normalized in _NETWORK_COMMAND_ALIASES:
        return _NETWORK_COMMAND_ALIASES[normalized]
    if is_network_operation:
        return normalized
    return None


def is_sensitive_path(path: str) -> bool:
    normalized = str(PurePath(path or '')).replace('\\', '/').lower()
    parts = [part.lower() for part in PurePath(path or '').parts]
    for sensitive in _SENSITIVE_PATH_PARTS:
        needle = sensitive.lower()
        if needle in normalized:
            return True
        if needle in parts:
            return True
    return False


def path_is_within_workspace(path: str | Path, workspace_root: str | Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(workspace_root).resolve())
        return True
    except ValueError:
        return False


def resolve_command_cwd(
    requested_cwd: str | None,
    *,
    workspace_root: str | Path,
    base_cwd: str | Path | None = None,
) -> Path:
    workspace = Path(workspace_root).resolve()
    base_path = Path(base_cwd).resolve() if base_cwd else workspace
    if not requested_cwd:
        return base_path
    requested = Path(requested_cwd)
    if requested.is_absolute():
        return requested.resolve()
    return (base_path / requested_cwd).resolve()


def evaluate_hardened_local_command_policy(
    *,
    command: str,
    security_config: Any,
    workspace_root: str | Path,
    requested_cwd: str | None,
    base_cwd: str | Path | None = None,
    is_background: bool = False,
) -> str | None:
    if not is_workspace_restricted_profile(security_config):
        return None

    if is_background and not getattr(
        security_config, 'allow_background_processes', False
    ):
        return (
            'Action blocked by hardened_local policy: background processes are disabled. '
            f'Command: {command}'
        )

    effective_cwd = resolve_command_cwd(
        requested_cwd,
        workspace_root=workspace_root,
        base_cwd=base_cwd,
    )
    if not path_is_within_workspace(effective_cwd, workspace_root):
        return (
            'Action blocked by hardened_local policy: command execution must stay inside the workspace. '
            f'Command: {command} | cwd={effective_cwd}'
        )

    git_subcommand = extract_git_subcommand(command or '')
    if git_subcommand is not None:
        if git_subcommand in normalize_allowlist(
            getattr(security_config, 'hardened_local_git_allowlist', ())
        ):
            return None
        return (
            'Action blocked by hardened_local policy: git '
            f'{git_subcommand} is not in the workspace-scoped allowlist for git subcommands. '
            f'Command: {command}'
        )

    package_key = classify_package_command(command or '')
    if package_key is not None:
        if getattr(security_config, 'allow_package_installs', False):
            return None
        if package_key in normalize_allowlist(
            getattr(security_config, 'hardened_local_package_allowlist', ())
        ):
            return None
        return (
            'Action blocked by hardened_local policy: '
            f'{package_key} is not in the workspace-scoped allowlist for package installation commands. '
            f'Command: {command}'
        )

    assessment = CommandAnalyzer().analyze_command(command)
    network_key = classify_network_command(
        command or '', assessment.is_network_operation
    )
    if network_key is not None:
        if getattr(security_config, 'allow_network_commands', False):
            return None
        if network_key in normalize_allowlist(
            getattr(security_config, 'hardened_local_network_allowlist', ())
        ):
            return None
        return (
            'Action blocked by hardened_local policy: '
            f'{network_key} is not in the workspace-scoped allowlist for network-capable commands. '
            f'Command: {command}'
        )

    return None


def evaluate_hardened_local_file_policy(
    *, path: str, security_config: Any
) -> str | None:
    if not is_workspace_restricted_profile(security_config):
        return None
    if is_sensitive_path(path) and not getattr(
        security_config, 'allow_sensitive_path_access', False
    ):
        return (
            'Action blocked by hardened_local policy: sensitive file access is disabled. '
            f'Path: {path}'
        )
    return None


class SecurityEnforcementMixin:
    """Mixin that gates action execution based on security risk assessment.

    Expects the host class to provide:
        - ``self.security_analyzer: SecurityAnalyzer | None``
        - ``self.config.security`` with ``enforce_security`` and ``block_high_risk``
    """

    security_analyzer: Any
    config: Any

    def _check_action_confirmation(self, action: Action) -> Observation | None:
        """Check action confirmation state and return appropriate observation."""
        from backend.ledger.action import (
            ActionConfirmationStatus,
            FileEditAction,
        )
        from backend.ledger.observation import NullObservation, UserRejectObservation

        if (
            hasattr(action, 'confirmation_state')
            and action.confirmation_state
            == ActionConfirmationStatus.AWAITING_CONFIRMATION
        ):
            # Allow file edits to run in runtime preview mode (dry-run) so users can
            # review diffs before confirming. Other actions remain blocked.
            if isinstance(action, FileEditAction):
                return None
            return NullObservation('')

        if (
            getattr(action, 'confirmation_state', None)
            == ActionConfirmationStatus.REJECTED
        ):
            return UserRejectObservation(
                'Action has been rejected by the user! Waiting for further user input.'
            )

        return None

    def _enforce_security(self, action: Action) -> Observation | None:
        """Evaluate action risk via SecurityAnalyzer and enforce policy.

        Returns:
            * ``None`` — action may proceed.
            * ``ErrorObservation`` — action is blocked (HIGH risk + ``block_high_risk``).
            * ``NullObservation`` — action needs user confirmation (HIGH risk, not blocking).
        """
        from backend.core.enums import ActionSecurityRisk
        from backend.ledger.action import ActionConfirmationStatus
        from backend.ledger.observation import ErrorObservation, NullObservation

        decision = self._evaluate_security_policy(action)

        if decision.block_message:
            return ErrorObservation(content=decision.block_message)

        risk = decision.risk
        if risk is None:
            return None

        if risk >= ActionSecurityRisk.HIGH:
            action_desc = f'{action.action}: {str(action)[:120]}'
            if decision.require_confirmation and (
                hasattr(action, 'confirmation_state')
                and action.confirmation_state != ActionConfirmationStatus.CONFIRMED
            ):
                logger.info(
                    'Security: requiring confirmation for high-risk action: %s',
                    action_desc,
                )
                action.confirmation_state = (
                    ActionConfirmationStatus.AWAITING_CONFIRMATION
                )  # type: ignore[union-attr]
                return NullObservation('')

        elif risk >= ActionSecurityRisk.MEDIUM:
            logger.info(
                'Security: medium-risk action allowed: %s (risk=%s)',
                action.action,
                risk.name,
            )

        return None

    def _evaluate_security_policy(self, action: Action) -> SecurityPolicyDecision:
        from backend.core.enums import ActionSecurityRisk
        from backend.ledger.action import ActionConfirmationStatus, CmdRunAction

        sec_cfg = self.config.security  # type: ignore[attr-defined]
        decision = SecurityPolicyDecision()

        if isinstance(action, CmdRunAction):
            editor_block = self._enforce_editor_only_shell_writes(action)
            if editor_block is not None:
                decision.block_message = editor_block
                return decision

        hardening_result = self._enforce_hardened_local_policy(action)
        if hardening_result is not None:
            decision.block_message = hardening_result.content
            return decision

        if not sec_cfg.enforce_security:
            return decision

        risk = self._resolve_security_risk(action)
        if risk is None:
            return decision
        decision.risk = risk

        if risk >= ActionSecurityRisk.HIGH:
            action_desc = f'{action.action}: {str(action)[:120]}'
            if sec_cfg.block_high_risk:
                logger.warning(
                    'Security BLOCKED high-risk action: %s (risk=%s)',
                    action_desc,
                    risk.name,
                )
                decision.block_message = f'Action blocked by security policy (risk={risk.name}). Action: {action_desc}'
                return decision
            if (
                hasattr(action, 'confirmation_state')
                and getattr(action, 'confirmation_state', None)
                != ActionConfirmationStatus.CONFIRMED
            ):
                decision.require_confirmation = True

        return decision

    def _resolve_security_risk(self, action: Action) -> Any | None:
        from backend.core.enums import ActionSecurityRisk

        existing_risk = getattr(action, 'security_risk', ActionSecurityRisk.UNKNOWN)
        if (
            isinstance(existing_risk, ActionSecurityRisk)
            and existing_risk != ActionSecurityRisk.UNKNOWN
        ):
            return existing_risk

        if self.security_analyzer is None:  # type: ignore[attr-defined]
            return None

        from backend.utils.async_utils import call_async_from_sync

        try:
            # ``call_async_from_sync`` routes through the bounded EXECUTOR with
            # task-cancellation timeouts, instead of plain ``asyncio.run`` which
            # creates an unbounded loop in the calling worker thread and would
            # raise ``RuntimeError`` if this is ever invoked from inside a
            # running event loop.
            risk = call_async_from_sync(
                self.security_analyzer.security_risk, 30.0, action
            )
            if hasattr(action, 'security_risk'):
                action.security_risk = risk
            return risk
        except Exception:
            logger.warning(
                'Security analysis failed for %s, allowing action to proceed',
                action.action,
                exc_info=True,
            )
            return None

    def _enforce_editor_only_shell_writes(self, action: Action) -> str | None:
        """Enforce editor tools for workspace file writes (CmdRunAction only)."""
        from backend.ledger.action import CmdRunAction

        if not isinstance(action, CmdRunAction):
            return None
        if getattr(action, 'is_static', False) or getattr(action, 'hidden', False):
            return None
        if getattr(action, 'is_input', False):
            return None
        sec_cfg = self.config.security  # type: ignore[attr-defined]
        return evaluate_editor_only_shell_block(
            command=action.command or '',
            security_config=sec_cfg,
            workspace_root=self._workspace_root_path(),
            cwd=getattr(action, 'cwd', None),
        )

    def _enforce_hardened_local_policy(self, action: Action) -> Observation | None:
        """Apply deterministic local policy gates before heuristic risk handling."""
        from backend.ledger.action import (
            CmdRunAction,
            FileEditAction,
            FileReadAction,
            FileWriteAction,
        )
        from backend.ledger.observation import ErrorObservation

        sec_cfg = self.config.security  # type: ignore[attr-defined]
        if not is_workspace_restricted_profile(sec_cfg):
            return None

        if isinstance(action, CmdRunAction):
            block_message = evaluate_hardened_local_command_policy(
                command=action.command or '',
                security_config=sec_cfg,
                workspace_root=self._workspace_root_path(),
                requested_cwd=getattr(action, 'cwd', None),
                is_background=getattr(action, 'is_background', False),
            )
            if block_message is not None:
                return ErrorObservation(content=block_message)

        if isinstance(action, (FileReadAction, FileWriteAction, FileEditAction)):
            block_message = evaluate_hardened_local_file_policy(
                path=getattr(action, 'path', ''),
                security_config=sec_cfg,
            )
            if block_message is not None:
                return ErrorObservation(content=block_message)

        return None

    def _enforce_workspace_allowlist(
        self,
        action: Action,
        *,
        allowlist: Any,
        command_key: str,
        category_label: str,
        command_label: str,
    ) -> Observation | None:
        from backend.ledger.observation import ErrorObservation

        if not self._is_workspace_scoped_command(action):
            cwd = getattr(action, 'cwd', None) or str(self._workspace_root_path())
            return ErrorObservation(
                content=(
                    f'Action blocked by hardened_local policy: {category_label} must run inside the workspace. '
                    f'Command: {getattr(action, "command", "")} | cwd={cwd}'
                )
            )

        normalized_allowlist = self._normalize_allowlist(allowlist)
        if command_key in normalized_allowlist:
            return None

        return ErrorObservation(
            content=(
                f'Action blocked by hardened_local policy: {command_label} is not in the workspace-scoped allowlist '
                f'for {category_label}. Command: {getattr(action, "command", "")}'
            )
        )

    def _normalize_allowlist(self, values: Any) -> set[str]:
        return normalize_allowlist(values)

    def _workspace_root_path(self) -> Path:
        raw_root = getattr(self, 'workspace_root', None)
        if raw_root is not None:
            return Path(raw_root).resolve()
        project_root = getattr(self, 'project_root', None)
        if project_root:
            return Path(project_root).resolve()
        return Path.cwd().resolve()

    def _resolve_command_cwd(self, action: Action) -> Path:
        workspace_root = self._workspace_root_path()
        raw_cwd = getattr(action, 'cwd', None)
        return resolve_command_cwd(
            raw_cwd,
            workspace_root=workspace_root,
        )

    def _is_workspace_scoped_command(self, action: Action) -> bool:
        workspace_root = self._workspace_root_path()
        try:
            self._resolve_command_cwd(action).relative_to(workspace_root)
            return True
        except ValueError:
            return False

    def _tokenize_command(self, command: str) -> list[str]:
        return tokenize_command(command)

    def _extract_git_subcommand(self, command: str) -> str | None:
        return extract_git_subcommand(command)

    def _classify_package_command(self, command: str) -> str | None:
        return classify_package_command(command)

    def _classify_network_command(
        self, command: str, is_network_operation: bool
    ) -> str | None:
        return classify_network_command(command, is_network_operation)

    def _is_sensitive_path(self, path: str) -> bool:
        return is_sensitive_path(path)
