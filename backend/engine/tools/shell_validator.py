"""Shell command validator to prevent environment mismatch loops.

Intercepts LLM-generated shell commands before execution to verify they
match the target shell environment (e.g. rejects bash 'grep' on PowerShell).
"""

from __future__ import annotations

import re

# Commands that are typically bash-specific and will fail on vanilla PowerShell
# (or provide unexpected Windows-specific aliases that confuse the LLM)
_FORBIDDEN_ON_POWERSHELL = {
    'grep', 'ls ', 'cat ', 'find ', 'chmod', 'sed', 'awk', 'which', 'pwd', 'rm ', 'mkdir ', 'touch '
}

# Commands that are PowerShell cmdlets and will fail on Bash
_FORBIDDEN_ON_BASH = {
    'Get-ChildItem', 'Get-Process', 'Get-Content', 'Select-String', 
    'Write-Output', 'Set-Location', 'ForEach-Object', 'Where-Object', 
    '$PSVersionTable', 'Invoke-WebRequest', 'Invoke-RestMethod', 'Resolve-Path'
}

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
        
    # Check for powershell context
    if is_powershell:
        # Check against forbidden bash commands
        for bad_cmd in _FORBIDDEN_ON_POWERSHELL:
            # Simple boundary check to avoid matching substrings like `igrep` or inside words
            if re.search(rf'\b{bad_cmd.strip()}\b', command):
                return (
                    f"[SHELL VALIDATOR] Error: The command '{bad_cmd.strip()}' is a Unix/Bash "
                    f"command and is not available or behaves differently in PowerShell. "
                    f"Please use native tools like `search_code`, `str_replace_editor` (view_file), "
                    f"or native PowerShell cmdlets to accomplish this task."
                )
    else:
        # Check against forbidden powershell commands
        for bad_cmd in _FORBIDDEN_ON_BASH:
            if re.search(rf'\b{re.escape(bad_cmd.replace("$", ""))}\b', command, flags=re.IGNORECASE):
                return (
                    f"[SHELL VALIDATOR] Error: The command '{bad_cmd}' is a PowerShell "
                    f"cmdlet and is not available in Bash. Please use Unix/Bash native "
                    f"commands or built-in tools like `search_code`."
                )
                
    return None
