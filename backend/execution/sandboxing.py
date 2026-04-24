"""Execution sandbox helpers for the ``sandboxed_local`` profile.

This module chooses the OS-specific sandbox backend and wraps command argv for
subprocess-backed shells:

- Linux: ``bubblewrap`` / ``bwrap``
- macOS: ``sandbox-exec``
- Windows: AppContainer helper launched via ``python -m``

The goal is honest isolation for non-interactive command execution. Interactive
terminal sessions are handled separately by the shell factory and are currently
disabled under ``sandboxed_local`` to avoid pretending they are isolated when
they are not.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Sequence


SandboxBackend = Literal['bubblewrap', 'sandbox-exec', 'appcontainer']
_SANDBOX_TMP_DIR = Path('/').joinpath('tmp').as_posix()


def is_sandboxed_local_profile(security_config: Any | None) -> bool:
    """Return True when the configured execution profile is ``sandboxed_local``."""
    return getattr(security_config, 'execution_profile', 'standard') == 'sandboxed_local'


def is_workspace_restricted_profile(security_config: Any | None) -> bool:
    """Profiles that must obey hardened workspace/path restrictions."""
    return getattr(security_config, 'execution_profile', 'standard') in {
        'hardened_local',
        'sandboxed_local',
    }


def _existing_paths(paths: Sequence[str]) -> list[str]:
    return [path for path in paths if os.path.exists(path)]


def _quote_sb_path(path: str) -> str:
    return path.replace('\\', '\\\\').replace('"', '\\"')


@dataclass(frozen=True)
class ExecutionSandboxPolicy:
    """Resolved sandbox backend plus argv-wrapping logic."""

    backend: SandboxBackend
    workspace_root: str
    allow_network: bool = False

    def wrap_argv(self, argv: Sequence[str], *, cwd: str) -> list[str]:
        """Return a sandbox-prefixed argv for the target child command."""
        if self.backend == 'bubblewrap':
            return self._wrap_bubblewrap(argv, cwd=cwd)
        if self.backend == 'sandbox-exec':
            return self._wrap_sandbox_exec(argv)
        if self.backend == 'appcontainer':
            return self._wrap_appcontainer(argv, cwd=cwd)
        raise RuntimeError(f'Unsupported sandbox backend: {self.backend}')

    def _wrap_bubblewrap(self, argv: Sequence[str], *, cwd: str) -> list[str]:
        launcher = shutil.which('bwrap') or shutil.which('bubblewrap')
        if not launcher:
            raise RuntimeError(
                "execution_profile='sandboxed_local' requires bubblewrap (`bwrap`) on Linux."
            )

        args: list[str] = [
            launcher,
            '--die-with-parent',
            '--new-session',
            '--proc',
            '/proc',
            '--dev',
            '/dev',
            '--tmpfs',
            _SANDBOX_TMP_DIR,
            '--setenv',
            'HOME',
            self.workspace_root,
            '--setenv',
            'TMPDIR',
            _SANDBOX_TMP_DIR,
        ]
        if not self.allow_network:
            args.append('--unshare-net')

        for path in _existing_paths(
            [
                '/bin',
                '/sbin',
                '/usr',
                '/lib',
                '/lib64',
                '/etc',
                '/opt',
                '/nix',
                '/run/current-system/sw',
            ]
        ):
            args.extend(['--ro-bind', path, path])

        args.extend(
            [
                '--bind',
                self.workspace_root,
                self.workspace_root,
                '--chdir',
                cwd,
                '--',
            ]
        )
        args.extend(list(argv))
        return args

    def _wrap_sandbox_exec(self, argv: Sequence[str]) -> list[str]:
        launcher = shutil.which('sandbox-exec')
        if not launcher:
            raise RuntimeError(
                "execution_profile='sandboxed_local' requires sandbox-exec on macOS."
            )

        workspace = _quote_sb_path(self.workspace_root)
        policy_lines = [
            '(version 1)',
            '(deny default)',
            '(import "system.sb")',
            '(allow process-exec)',
            '(allow process-fork)',
            '(allow sysctl-read)',
            '(allow mach-lookup)',
            '(allow signal (target self))',
            '(allow file-read*',
            '    (subpath "/bin")',
            '    (subpath "/usr")',
            '    (subpath "/System")',
            '    (subpath "/Library")',
            '    (subpath "/private/etc")',
            '    (subpath "/tmp")',
            '    (subpath "/private/tmp")',
            f'    (subpath "{workspace}")',
            ')',
            '(allow file-write*',
            '    (subpath "/tmp")',
            '    (subpath "/private/tmp")',
            f'    (subpath "{workspace}")',
            ')',
        ]
        if self.allow_network:
            policy_lines.append('(allow network*)')
        else:
            policy_lines.append('(deny network*)')

        args = [launcher, '-p', '\n'.join(policy_lines)]
        args.extend(list(argv))
        return args

    def _wrap_appcontainer(self, argv: Sequence[str], *, cwd: str) -> list[str]:
        return [
            sys.executable,
            '-m',
            'backend.execution.sandbox_helpers.appcontainer_runner',
            '--workspace',
            self.workspace_root,
            '--cwd',
            cwd,
            '--network',
            '1' if self.allow_network else '0',
            '--',
            *list(argv),
        ]


def resolve_execution_sandbox_policy(
    *,
    security_config: Any | None,
    workspace_root: str | Path,
) -> ExecutionSandboxPolicy | None:
    """Return the active sandbox policy, or ``None`` if sandboxing is disabled."""
    if not is_sandboxed_local_profile(security_config):
        return None

    workspace = str(Path(workspace_root).resolve())
    allow_network = bool(getattr(security_config, 'allow_network_commands', False))

    if sys.platform == 'linux':
        if not (shutil.which('bwrap') or shutil.which('bubblewrap')):
            raise RuntimeError(
                "execution_profile='sandboxed_local' requires bubblewrap (`bwrap`) on Linux."
            )
        return ExecutionSandboxPolicy(
            backend='bubblewrap',
            workspace_root=workspace,
            allow_network=allow_network,
        )

    if sys.platform == 'darwin':
        if not shutil.which('sandbox-exec'):
            raise RuntimeError(
                "execution_profile='sandboxed_local' requires sandbox-exec on macOS."
            )
        return ExecutionSandboxPolicy(
            backend='sandbox-exec',
            workspace_root=workspace,
            allow_network=allow_network,
        )

    if sys.platform == 'win32':
        return ExecutionSandboxPolicy(
            backend='appcontainer',
            workspace_root=workspace,
            allow_network=allow_network,
        )

    raise RuntimeError(
        f"execution_profile='sandboxed_local' is not supported on platform {sys.platform}."
    )


__all__ = [
    'ExecutionSandboxPolicy',
    'is_sandboxed_local_profile',
    'is_workspace_restricted_profile',
    'resolve_execution_sandbox_policy',
]