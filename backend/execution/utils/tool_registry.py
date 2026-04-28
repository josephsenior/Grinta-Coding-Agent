"""Tool detection and registry for cross-platform runtime.

Detects available tools at startup and provides fallback strategies.
Inspired by VS Code's approach to cross-platform compatibility.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Literal

from backend.core.logger import app_logger as logger
from backend.core.os_capabilities import OS_CAPS


def resolve_windows_powershell_preference(
    *, has_bash: bool, has_powershell: bool
) -> bool:
    """Return True when Windows terminal contract should use PowerShell.

    Preference is controlled by ``APP_WINDOWS_SHELL_PREFERENCE`` with values:

    - ``powershell`` (default): use PowerShell when available, else bash fallback
    - ``bash``: prefer Git Bash when available
    - ``auto``: currently equivalent to ``powershell``
    """
    if not OS_CAPS.is_windows:
        return False

    raw_pref = os.getenv('APP_WINDOWS_SHELL_PREFERENCE', 'powershell').strip().lower()
    if raw_pref in {'bash', 'git-bash', 'gitbash', 'posix'}:
        return False if has_bash else has_powershell

    # Default and auto behavior: prefer PowerShell when available.
    return has_powershell


@dataclass
class ToolInfo:
    """Information about a detected tool."""

    name: str
    available: bool
    path: str | None = None
    version: str | None = None
    fallback: str | None = None


class ToolRegistry:
    """Registry of available tools detected at startup.

    This class detects tools once at initialization and caches the results
    for performance. It provides a consistent interface for checking tool
    availability and getting fallback strategies. It is implemented as a Singleton.
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        """Initialize and detect all tools."""
        if getattr(self, '_initialized', False):
            return

        self._tools: dict[str, ToolInfo] = {}
        self._is_container = self._detect_container_runtime()
        self._is_wsl = self._detect_wsl_runtime()
        self._detect_all_tools()
        self._initialized = True

    def _detect_container_runtime(self) -> bool:
        if os.getenv('APP_RUNTIME_IS_CONTAINER', '').strip().lower() in {
            '1',
            'true',
            'yes',
            'on',
        }:
            return True
        if os.getenv('container', '').strip():
            return True
        return os.path.exists('/.dockerenv') or os.path.exists('/run/.containerenv')

    def _detect_wsl_runtime(self) -> bool:
        platform_name = getattr(sys, 'platform', '')
        if not str(platform_name).startswith('linux'):
            return False
        if os.getenv('WSL_DISTRO_NAME') or os.getenv('WSL_INTEROP'):
            return True
        try:
            with open('/proc/version', encoding='utf-8') as f:
                return 'microsoft' in f.read().lower()
        except OSError:
            return False

    def _detect_all_tools(self) -> None:
        """Detect all tools at once during initialization."""
        logger.info('🔍 Detecting available tools...')

        # Detect shell
        self._detect_shell()

        # Detect search tools
        self._detect_search_tool()

        # Detect Git (required)
        self._detect_git()

        # Detect tmux (Unix only, optional)
        self._detect_tmux()

        # Log summary
        self._log_detection_summary()

    def _detect_shell(self) -> None:
        """Detect the best available shell."""
        if OS_CAPS.is_windows:
            # Windows: try pwsh -> powershell -> cmd
            if self._check_command(
                'pwsh', ['-NoProfile', '-Command', '$PSVersionTable.PSVersion']
            ):
                self._tools['shell'] = ToolInfo(
                    name='pwsh',
                    available=True,
                    path=shutil.which('pwsh'),
                    version=self._get_powershell_version('pwsh'),
                )
            elif self._check_command(
                'powershell', ['-NoProfile', '-Command', '$PSVersionTable.PSVersion']
            ):
                self._tools['shell'] = ToolInfo(
                    name='powershell',
                    available=True,
                    path=shutil.which('powershell'),
                    version=self._get_powershell_version('powershell'),
                )
            else:
                # Fallback to cmd (always available on Windows)
                self._tools['shell'] = ToolInfo(
                    name='cmd',
                    available=True,
                    path=shutil.which('cmd'),
                )
            # Also detect bash availability (Git Bash / WSL) on Windows
            bash_path = shutil.which('bash')
            if bash_path and self._check_command('bash', ['--version']):
                self._tools['bash'] = ToolInfo(
                    name='bash',
                    available=True,
                    path=bash_path,
                    version=self._get_bash_version(),
                )
        else:
            # Unix-like: try bash (should always be available)
            bash_path = shutil.which('bash')
            if bash_path:
                self._tools['shell'] = ToolInfo(
                    name='bash',
                    available=True,
                    path=bash_path,
                    version=self._get_bash_version(),
                )
            else:
                # Fallback to sh (POSIX standard)
                self._tools['shell'] = ToolInfo(
                    name='sh',
                    available=True,
                    path=shutil.which('sh'),
                )

    def _detect_search_tool(self) -> None:
        """Detect the best available search tool."""
        # Try ripgrep first (fastest)
        if self._check_command('rg', ['--version']):
            self._tools['search'] = ToolInfo(
                name='ripgrep',
                available=True,
                path=shutil.which('rg'),
                version=self._get_version_output('rg', ['--version']),
            )
        # Try grep (Unix standard)
        elif self._check_command('grep', ['--version']):
            self._tools['search'] = ToolInfo(
                name='grep',
                available=True,
                path=shutil.which('grep'),
                fallback='python',  # Can fall back to pure Python
            )
        # Windows findstr
        elif OS_CAPS.is_windows and self._check_command(
            'findstr', ['/?'], check_stderr=True
        ):
            self._tools['search'] = ToolInfo(
                name='findstr',
                available=True,
                path=shutil.which('findstr'),
                fallback='python',
            )
        else:
            # Pure Python fallback (always works)
            self._tools['search'] = ToolInfo(
                name='python',
                available=True,
                fallback=None,  # No further fallback
            )

    def _detect_git(self) -> None:
        """Detect Git (required tool)."""
        if self._check_command('git', ['--version']):
            self._tools['git'] = ToolInfo(
                name='git',
                available=True,
                path=shutil.which('git'),
                version=self._get_version_output('git', ['--version']),
            )
        else:
            self._tools['git'] = ToolInfo(
                name='git',
                available=False,
            )

    def _detect_tmux(self) -> None:
        """Detect tmux (Unix only, optional)."""
        if OS_CAPS.is_windows:
            # tmux not available on Windows
            self._tools['tmux'] = ToolInfo(
                name='tmux',
                available=False,
            )
        elif self._check_command('tmux', ['-V']):
            self._tools['tmux'] = ToolInfo(
                name='tmux',
                available=True,
                path=shutil.which('tmux'),
                version=self._get_version_output('tmux', ['-V']),
            )
        else:
            self._tools['tmux'] = ToolInfo(
                name='tmux',
                available=False,
                fallback='subprocess',  # Can use simple subprocess instead
            )

    def _check_command(
        self,
        command: str,
        args: list[str],
        check_stderr: bool = False,
    ) -> bool:
        """Check if a command is available and working."""
        try:
            result = subprocess.run(
                [command, *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            # Some commands (like findstr) output to stderr
            if check_stderr:
                return result.returncode == 0 or bool(result.stderr)
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError):
            return False

    def _get_version_output(self, command: str, args: list[str]) -> str | None:
        """Get version output from a command."""
        try:
            result = subprocess.run(
                [command, *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip().split('\n')[0]  # First line only
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return None

    def _get_powershell_version(self, ps_exe: str) -> str | None:
        """Get PowerShell version."""
        try:
            result = subprocess.run(
                [
                    ps_exe,
                    '-NoProfile',
                    '-Command',
                    '$PSVersionTable.PSVersion.ToString()',
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return None

    def _get_bash_version(self) -> str | None:
        """Get Bash version."""
        try:
            result = subprocess.run(
                ['bash', '--version'],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                # Extract version from first line
                return result.stdout.split('\n')[0]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return None

    def _log_detection_summary(self) -> None:
        """Log a summary of detected tools."""
        logger.info(
            'Runtime context: platform=%s container=%s wsl=%s',
            sys.platform,
            self._is_container,
            self._is_wsl,
        )
        for tool_name, tool_info in self._tools.items():
            if tool_info.available:
                version_str = f' ({tool_info.version})' if tool_info.version else ''
                logger.info(
                    '✅ %s: %s%s', tool_name.capitalize(), tool_info.name, version_str
                )
            else:
                fallback_str = (
                    f' (fallback: {tool_info.fallback})' if tool_info.fallback else ''
                )
                if tool_name == 'git':
                    logger.error(
                        '❌ %s: Not found (REQUIRED)%s',
                        tool_name.capitalize(),
                        fallback_str,
                    )
                elif tool_name == 'tmux' and OS_CAPS.is_windows:
                    logger.debug(
                        '⚠️  %s: Not available on Windows (expected)',
                        tool_name.capitalize(),
                    )
                else:
                    logger.warning(
                        '⚠️  %s: Not found%s', tool_name.capitalize(), fallback_str
                    )

    # Public API

    @property
    def shell_type(self) -> Literal['bash', 'pwsh', 'powershell', 'cmd', 'sh']:
        """Get the detected shell type."""
        return self._tools.get('shell', ToolInfo('unknown', False)).name  # type: ignore

    @property
    def has_bash(self) -> bool:
        """Check if bash is available (as primary shell or as a separate tool on Windows)."""
        if self._tools.get('shell', ToolInfo('', False)).name == 'bash':
            return True
        # On Windows, bash may be available as a separate tool (Git Bash / WSL)
        return self._tools.get('bash', ToolInfo('', False)).available

    @property
    def has_powershell(self) -> bool:
        """Check if PowerShell is available."""
        shell = self._tools.get('shell', ToolInfo('', False)).name
        return shell in ('pwsh', 'powershell')

    @property
    def prefers_powershell_on_windows(self) -> bool:
        """Check whether Windows shell contract should prefer PowerShell."""
        return resolve_windows_powershell_preference(
            has_bash=self.has_bash,
            has_powershell=self.has_powershell,
        )

    @property
    def has_tmux(self) -> bool:
        """Check if tmux is available."""
        return self._tools.get('tmux', ToolInfo('', False)).available

    @property
    def has_git(self) -> bool:
        """Check if Git is available."""
        return self._tools.get('git', ToolInfo('', False)).available

    @property
    def search_tool(self) -> Literal['ripgrep', 'grep', 'findstr', 'python']:
        """Get the detected search tool."""
        return self._tools.get('search', ToolInfo('python', True)).name  # type: ignore

    @property
    def has_ripgrep(self) -> bool:
        """Check if ripgrep is available."""
        return self._tools.get('search', ToolInfo('', False)).name == 'ripgrep'

    @property
    def is_container_runtime(self) -> bool:
        """True when running in a containerized runtime."""
        return self._is_container

    @property
    def is_wsl_runtime(self) -> bool:
        """True when running under Windows Subsystem for Linux."""
        return self._is_wsl

    def get_tool_info(self, tool_name: str) -> ToolInfo | None:
        """Get detailed information about a tool."""
        return self._tools.get(tool_name)

    def require_git(self) -> None:
        """Ensure Git is available, raise if not."""
        if not self.has_git:
            raise RuntimeError(
                'Git is required but not found.\nInstall Git from: https://git-scm.com/downloads'
            )
