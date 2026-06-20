"""Command execution and validation helpers extracted from :class:`BashSession`.

These functions implement ``execute()`` and the validation/output
post-processing helpers it composes. ``_monitor_command_execution`` is in
:mod:`_bash_timeouts` because it is the timeout-driven state machine.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from backend.core.logging.logger import app_logger as logger
from backend.execution.utils.shell.bash_support import split_bash_commands
from backend.ledger.observation import ErrorObservation
from backend.ledger.observation.commands import (
    CMD_OUTPUT_PS1_END,
    CmdOutputMetadata,
    CmdOutputObservation,
)

if TYPE_CHECKING:
    from backend.execution.utils.shell.bash import BashSession
    from backend.ledger.action import CmdRunAction

Ps1Match = Any  # alias: re.Match[str]


def _is_special_key(orch: BashSession, command: str) -> bool:
    """Check if the command is a special key."""
    del orch  # instance kept for API uniformity; no per-session state needed
    _command = command.strip()
    return _command.startswith('C-') and len(_command) == 3


def _validate_session_and_command(orch: BashSession, action: CmdRunAction) -> None:
    """Validate session is initialized and command is valid."""
    from backend.execution.utils.shell.bash import BashCommandStatus

    if not orch._initialized:
        msg = 'Bash session is not initialized'
        raise RuntimeError(msg)

    logger.debug('RECEIVED ACTION: %s', action)

    command = action.command.strip()
    if orch.prev_status not in {
        BashCommandStatus.CONTINUE,
        BashCommandStatus.NO_CHANGE_TIMEOUT,
        BashCommandStatus.HARD_TIMEOUT,
    }:
        if command == '':
            msg = 'ERROR: No previous running command to retrieve logs from.'
            raise ValueError(msg)
        is_input: bool = action.is_input

        if is_input:
            msg = 'ERROR: No previous running command to interact with.'
            raise ValueError(msg)

    splited_commands = split_bash_commands(command)
    if len(splited_commands) > 1:
        provided_commands = '\n'.join(
            f'({index + 1}) {cmd}' for index, cmd in enumerate(splited_commands)
        )
        msg = (
            'ERROR: Cannot execute multiple commands at once.\n'
            'Please run each command separately OR chain them into a single '
            'command via && or ;\n'
            f'Provided commands:\n{provided_commands}'
        )
        raise ValueError(
            msg,
        )


def _combine_outputs_between_matches(
    orch: BashSession,
    pane_content: str,
    ps1_matches: list[Ps1Match],
    get_content_before_last_match: bool = False,
) -> str:
    """Combine all outputs between PS1 matches.

    Args:
        orch: The ``BashSession`` instance (unused; kept for API uniformity).
        pane_content: The full pane content containing PS1 prompts and command outputs
        ps1_matches: List of regex matches for PS1 prompts
        get_content_before_last_match: when there's only one PS1 match, whether to get
            the content before the last PS1 prompt (True) or after the last PS1 prompt (False)

    Returns:
        Combined string of all outputs between matches

    """
    del orch  # instance kept for API uniformity; no per-session state needed
    if len(ps1_matches) == 1:
        if get_content_before_last_match:
            return pane_content[: ps1_matches[0].start()]
        return pane_content[ps1_matches[0].end() + 1 :]
    if not ps1_matches:
        return pane_content
    combined_output = ''
    for i in range(len(ps1_matches) - 1):
        output_segment = pane_content[
            ps1_matches[i].end() + 1 : ps1_matches[i + 1].start()
        ]
        combined_output += output_segment + '\n'
    combined_output += pane_content[ps1_matches[-1].end() + 1 :]
    logger.debug('COMBINED OUTPUT: %s', combined_output)
    return combined_output


def _check_command_completion(
    orch: BashSession,
    cur_pane_output: str,
    ps1_matches: list[Ps1Match],
    initial_ps1_count: int,
    command: str,
    is_input: bool,
) -> CmdOutputObservation | None:
    """Check if command has completed and return observation if so."""
    current_ps1_count = len(ps1_matches)
    if current_ps1_count > initial_ps1_count or cur_pane_output.rstrip().endswith(
        CMD_OUTPUT_PS1_END.rstrip()
    ):
        return orch._handle_completed_command(
            command,
            pane_content=cur_pane_output,
            ps1_matches=ps1_matches,
            hidden=False,
            is_input=is_input,
        )
    return None


def _handle_interactive_prompts(orch: BashSession, output: str, is_input: bool) -> bool:
    """Check for interactive prompts and respond if detected."""
    # Deferred import: the test suite patches
    # ``backend.execution.utils.shell.bash.detect_interactive_prompt``, so we must
    # resolve the symbol via the ``bash`` module (not via
    # ``prompt_detector`` directly) for ``mock.patch`` to see the override.
    from backend.execution.utils.shell.bash import detect_interactive_prompt

    is_prompt, response = detect_interactive_prompt(output)
    if is_prompt and response:
        logger.info(
            '🤖 Auto-responding to interactive prompt with: %r',
            response,
        )
        orch._send_command_to_pane(response, is_input=True)
        # Give the system time to process the input
        time.sleep(0.2)
        return True
    return False


def execute(
    orch: BashSession, action: CmdRunAction
) -> CmdOutputObservation | ErrorObservation:
    """Execute a command in the bash session."""
    try:
        # Validate session and command
        _validate_session_and_command(orch, action)
    except ValueError as e:
        if 'No previous running command' in str(e):
            return CmdOutputObservation(
                content=str(e), command='', metadata=CmdOutputMetadata()
            )
        return ErrorObservation(content=str(e))

    command = action.command.strip()
    is_input: bool = action.is_input

    # Verify tmux session is alive; auto-recover if dead
    if orch._ensure_session_alive():
        logger.info('[SESSION_RECOVERED] Tmux session was re-created')

    # Get initial state
    initial_pane_output = orch._get_pane_content()
    from backend.execution.utils.shell.bash import _matches_ps1_metadata

    initial_ps1_matches = _matches_ps1_metadata(initial_pane_output)
    initial_ps1_count = len(initial_ps1_matches)
    logger.debug('Initial PS1 count: %s', initial_ps1_count)

    if timeout_result := orch._handle_previous_command_timeout(
        command,
        initial_pane_output,
        initial_ps1_matches,
        is_input,
    ):
        return timeout_result

    # Send command to pane
    orch._send_command_to_pane(command, is_input)

    # Monitor execution
    return orch._monitor_command_execution(
        command,
        initial_ps1_count,
        is_input,
        action,
        initial_pane_output=initial_pane_output,
    )
