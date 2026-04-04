"""Shared utilities for shell sessions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.ledger.observation import CmdOutputMetadata, CmdOutputObservation

if TYPE_CHECKING:
    pass


def format_shell_output(
    command: str,
    stdout: str,
    stderr: str,
    exit_code: int,
    working_dir: str,
) -> CmdOutputObservation:
    """Format the results of a command execution into an observation.

    Args:
        command: The command that was executed
        stdout: Standard output from the command
        stderr: Standard error from the command
        exit_code: Exit code of the command
        working_dir: Current working directory

    Returns:
        Formatted CmdOutputObservation
    """
    content_parts = []
    if stdout:
        content_parts.append(stdout)
    if stderr:
        content_parts.append('[ERROR STREAM]\n' + stderr)

    final_content = '\n'.join(content_parts).strip()

    # Normalize working directory for Windows if needed
    normalized_cwd = (
        working_dir.replace('\\', '\\\\') if '\\' in working_dir else working_dir
    )

    metadata = CmdOutputMetadata(
        exit_code=exit_code,
        working_dir=normalized_cwd,
    )
    metadata.prefix = '[Below is the output of the previous command.]\n'
    metadata.suffix = f'\n[The command completed with exit code {exit_code}.]'

    return CmdOutputObservation(
        content=final_content,
        command=command,
        metadata=metadata,
    )
