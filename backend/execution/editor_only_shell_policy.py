"""Block shell-level project file writes so agents use editor tools instead.

This is deterministic policy (not prompt-only): execute_bash / execute_powershell
cannot replace str_replace_editor / ast_code_editor for creating or overwriting
source and document files.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

# PowerShell cmdlets that write file contents (not just metadata).
_PS_FILE_WRITER = re.compile(
    r'(?i)\b(?:Set-Content|Add-Content|Out-File|Export-Csv|Export-Clixml)\b'
)
# New-Item creating a file (empty or from -Value)
_PS_NEW_FILE = re.compile(r'(?i)\bNew-Item\b.*\b(?:-ItemType\s+File|\b-File\b)')

# Commands whose primary role is package / build / orchestration (may write under tree).
_TOOLCHAIN_LINE = re.compile(
    r'(?im)^\s*(?:git|docker|docker-compose|kubectl|helm|terraform|cargo|rustc|go|npm|pnpm|yarn|npx|pip|pip3|pipx|uv|poetry|conda|mvn|gradle|javac|make|ninja|cmake|msbuild|dotnet|protoc|winget|choco)\b'
)
# Chained: ... && make, ... ; cargo
_TOOLCHAIN_ANYWHERE = re.compile(
    r'(?i)(?:^|[;&|]|\b&&\b|\|\|)\s*(?:git|docker|docker-compose|kubectl|cargo|npm|pnpm|yarn|npx|pip|pip3|uv|make|ninja|cmake|dotnet|winget|choco)\b'
)

_TEMP_HINT = re.compile(
    r'(?i)([/\\]temp[/\\]|\$env:temp|%temp%|/tmp(?:/|$)|/var/folders/|[/\\]appdata[/\\]local[/\\]temp|\btmp\.[a-z0-9]{3,8}\b)'
)

# Server / build logs — allow shell redirection to these.
_LOG_OR_TMP_SUFFIX = re.compile(r'(?i)\.(?:log|tmp)(?:\s|$|"|\')')


def _command_targets_only_logs_or_temp(command: str) -> bool:
    """Heuristic: cmdlet/redirection only touches .log/.tmp or a temp directory."""
    if _TEMP_HINT.search(command):
        return True
    # Set-Content foo.log ...
    if _LOG_OR_TMP_SUFFIX.search(command):
        return True
    return False


def _powershell_write_blocked(command: str) -> bool:
    if not (_PS_FILE_WRITER.search(command) or _PS_NEW_FILE.search(command)):
        return False
    if _command_targets_only_logs_or_temp(command):
        return False
    return True


def _redirection_write_blocked(command: str) -> bool:
    """True if a shell redirect writes to a non-log file (stdout/err to file)."""
    if _TEMP_HINT.search(command):
        return False
    # Match > or >> targets; skip 2>&1 style when it's only merging streams into prior redirect.
    for m in re.finditer(
        r'(?m)(?<![<\d])\s>{1,2}\s*(?!>)([^\s|;&`]+)',
        command,
    ):
        target = m.group(1).strip('`"\'')
        if not target or target in {'&1', '&2', '-'}:
            continue
        if target.lower() in {
            '/dev/null',
            'nul',
            '$null',
            '/dev/stdout',
            '/dev/stderr',
        }:
            continue
        if target.lower().endswith(('.log', '.tmp')):
            continue
        # Windows NUL / null device
        if re.match(r'(?i)nul$', target):
            continue
        return True
    return False


def _tee_blocked(command: str) -> bool:
    if not re.search(r'(?i)(?:^|[\s;|])\btee\b', command):
        return False
    if _LOG_OR_TMP_SUFFIX.search(command) or _TEMP_HINT.search(command):
        return False
    return True


def _dd_blocked(command: str) -> bool:
    if not re.search(r'(?i)\bdd\b', command):
        return False
    if not re.search(r'(?i)\bof=', command):
        return False
    return not _TEMP_HINT.search(command)


def _likely_toolchain_command(command: str) -> bool:
    first = command.lstrip()
    if _TOOLCHAIN_LINE.match(first):
        return True
    return bool(_TOOLCHAIN_ANYWHERE.search(command))


def _env_allow_shell_writes() -> bool:
    """``GRINTA_ALLOW_SHELL_WRITES`` global override.

    Setting this to ``1/true/yes/on`` force-allows shell writes regardless
    of the security config — matching OpenCode and Claude Code, which
    expose a full shell tool without blanket file-write bans. Useful for
    one-off scripted scaffolding sessions.
    """
    raw = os.environ.get('GRINTA_ALLOW_SHELL_WRITES', '').strip().lower()
    return raw in {'1', 'true', 'yes', 'on'}


def evaluate_editor_only_shell_block(
    *,
    command: str,
    security_config: Any,
    workspace_root: str | Path,
    cwd: str | Path | None = None,
) -> str | None:
    """Return an error message if this shell command must not run, else None.

    Precedence:

    1. ``GRINTA_ALLOW_SHELL_WRITES=1`` env var → always allow.
    2. ``security_config.require_editor_for_shell_file_writes=False`` → allow.
    3. Otherwise run the pattern checks and block Set-Content/Out-File/
       redirection/tee/dd when they target non-log files.

    workspace_root and cwd are reserved for future path-precision checks
    (e.g. only block writes outside the workspace).
    """
    _ = Path(workspace_root)
    _ = cwd
    if _env_allow_shell_writes():
        return None
    if not getattr(security_config, 'require_editor_for_shell_file_writes', True):
        return None

    cmd = (command or '').strip()
    if not cmd:
        return None

    if _likely_toolchain_command(cmd):
        return None

    if _powershell_write_blocked(cmd):
        return _BLOCK_MSG

    if _redirection_write_blocked(cmd):
        return _BLOCK_MSG

    if _tee_blocked(cmd):
        return _BLOCK_MSG

    if _dd_blocked(cmd):
        return _BLOCK_MSG

    return None


_BLOCK_MSG = (
    'Shell file creation/overwrites are disabled for project work. '
    'Use the editor tools instead: '
    '`str_replace_editor` (create_file, insert_text, edit_mode) or '
    '`ast_code_editor` (create_file, replace_range, …). '
    'Do not use Set-Content, Out-File, tee, or `>` / `>>` to write source or '
    'document files. Redirection to `.log` / `.tmp` or a temp path is still allowed. '
    'If you really need shell writes (e.g. scaffolding scripts), set the '
    'environment variable GRINTA_ALLOW_SHELL_WRITES=1.'
)
