"""Renderer for the security risk policy block."""

from __future__ import annotations


def _render_security(cli_mode: bool = True) -> str:
    risk_block = (
        '- **LOW**: Safe, read-only actions.\n'
        '  - Viewing/summarizing content, reading project files, simple in-memory calculations.\n'
        '- **MEDIUM**: Project-scoped edits or execution.\n'
        '  - Modify user project files, run project scripts/tests, install project-local packages.\n'
        '- **HIGH**: System-level or untrusted operations.\n'
        '  - Changing system settings, global installs, elevated (`sudo`) commands, deleting critical files, '
        'downloading & executing untrusted code, or sending local secrets/data out.'
    )
    return (
        '# 🔐 Security Risk Policy\n'
        '`security_risk` is **required** on every call to `execute_bash`/`execute_powershell`, '
        'and the file write tools `create`, `replace_string`, `edit_symbols`, and `multiedit`. '
        'Read-only tools (`read`, `find_symbols`) do **not** require it. '
        'Pick one of `LOW` / `MEDIUM` / `HIGH` based on the action you are about to take. '
        'The server may escalate your risk label; it never lowers it. Missing or invalid values '
        'fail the call.\n\n'
        f'{risk_block}\n\n'
        '**Global Rules**\n'
        '- Always escalate to **HIGH** if sensitive data leaves the environment.\n'
        '- Long-running shell commands: pass an explicit `timeout` (seconds) instead of '
        'guessing.\n'
        '- For servers and log tails, use `is_background=true` on shell executors.'
    )
