"""Shell command validator to prevent environment mismatch loops.

Intercepts LLM-generated shell commands before execution to verify they
match the target shell environment (e.g. rejects bash 'grep -rn' on PowerShell).
"""

from __future__ import annotations

import re

# Unix-specific command patterns that WILL fail on vanilla PowerShell.
# These are patterns (not just command names) because some names like 'ls'
# are aliased in PowerShell and work fine on their own.
_FORBIDDEN_ON_POWERSHELL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # grep with flags — the core offender
    (re.compile(r'\bgrep\s+-'), 'grep (with flags)'),
    # find with Unix-syntax flags
    (re.compile(r'\bfind\s+\S+\s+-(?:name|type|maxdepth|exec|print)'), 'find (Unix syntax)'),
    # chmod / chown — never exist on Windows
    (re.compile(r'\b(?:chmod|chown)\s'), 'chmod/chown'),
    # sed with expressions
    (re.compile(r'\bsed\s+-?[ie]?\s'), 'sed'),
    # awk
    (re.compile(r'\bawk\s'), 'awk'),
    # which (use Get-Command on PS)
    (re.compile(r'\bwhich\s'), 'which'),
    # Unix-style piping through head/tail/wc
    (re.compile(r'\|\s*(?:head|tail|wc)\b'), 'head/tail/wc (pipe)'),
    # cat with path (not just bare 'cat' which is aliased)
    (re.compile(r'\bcat\s+["\']?(?:[./~]|[a-zA-Z]:)'), 'cat (file read)'),
    # source command
    (re.compile(r'\bsource\s'), 'source'),
    # bash-specific redirects
    (re.compile(r'2>&1'), '2>&1 (bash redirect syntax)'),
]

# PowerShell cmdlets that will fail on Bash
_FORBIDDEN_ON_BASH_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r'\bGet-ChildItem\b', re.IGNORECASE), 'Get-ChildItem'),
    (re.compile(r'\bGet-Process\b', re.IGNORECASE), 'Get-Process'),
    (re.compile(r'\bGet-Content\b', re.IGNORECASE), 'Get-Content'),
    (re.compile(r'\bSelect-String\b', re.IGNORECASE), 'Select-String'),
    (re.compile(r'\bWrite-Output\b', re.IGNORECASE), 'Write-Output'),
    (re.compile(r'\bSet-Location\b', re.IGNORECASE), 'Set-Location'),
    (re.compile(r'\bForEach-Object\b', re.IGNORECASE), 'ForEach-Object'),
    (re.compile(r'\bWhere-Object\b', re.IGNORECASE), 'Where-Object'),
    (re.compile(r'\bInvoke-WebRequest\b', re.IGNORECASE), 'Invoke-WebRequest'),
    (re.compile(r'\bInvoke-RestMethod\b', re.IGNORECASE), 'Invoke-RestMethod'),
    (re.compile(r'\$PSVersionTable\b'), '$PSVersionTable'),
]


def validate_shell_command(command: str, is_powershell: bool) -> str | None:
    """Validate a shell command against the current environment.

    Args:
        command: The raw shell command string.
        is_powershell: True if the execution environment is PowerShell.

    Returns:
        An actionable error message if the command is forbidden, else None.
    """
    if not command or not isinstance(command, str):
        return None

    patterns = _FORBIDDEN_ON_POWERSHELL_PATTERNS if is_powershell else _FORBIDDEN_ON_BASH_PATTERNS

    for pattern, name in patterns:
        if pattern.search(command):
            if is_powershell:
                return (
                    f"[SHELL VALIDATOR] Error: '{name}' is Unix/Bash syntax and will not "
                    f"work in PowerShell. Use native tools like `search_code`, "
                    f"`str_replace_editor` (view_file), or PowerShell cmdlets instead."
                )
            else:
                return (
                    f"[SHELL VALIDATOR] Error: '{name}' is a PowerShell cmdlet and will not "
                    f"work in Bash. Use Unix/Bash commands or `search_code` instead."
                )

    return None
