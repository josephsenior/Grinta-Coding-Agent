"""Timeout and command-monitoring state machine extracted from :class:`BashSession`.

This module is the largest single concern in :class:`BashSession`: the
state machine that polls the tmux pane, decides whether a command
completed normally, hit the no-change (idle) timeout, or hit the hard
timeout, and constructs the appropriate ``CmdOutputObservation`` for
each path.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from backend.core.logging.logger import app_logger as logger
from backend.execution.utils.shell.bash_constants import TIMEOUT_MESSAGE_TEMPLATE
from backend.ledger.observation.commands import (
    CMD_OUTPUT_PS1_END,
    CmdOutputMetadata,
    CmdOutputObservation,
)
from backend.utils.shutdown_listener import should_continue

if TYPE_CHECKING:
    from backend.execution.utils.shell.bash import BashSession
    from backend.ledger.action import CmdRunAction

Ps1Match = Any  # alias: re.Match[str]


def _match_ps1(content: str) -> list[Ps1Match]:
    """Match PS1 prompts in pane content.

    Local-imported to avoid a circular dependency: ``bash.py`` imports from
    this module, so we cannot import ``bash.py`` at module load time.
    """
    from backend.execution.utils.shell.bash import _matches_ps1_metadata

    return _matches_ps1_metadata(content)


def _kill_hung_process(orch: BashSession) -> None:
    r"""Escalate kill signals to terminate a hung foreground process.

    Sends SIGINT (Ctrl+C) first, waits briefly for the shell prompt to
    return.  If the process survives, sends SIGQUIT (Ctrl+\\) and finally
    falls back to ``kill -9 0`` which terminates the entire foreground
    process group in the tmux pane.
    """
    pane = orch._require_pane()

    def _prompt_returned() -> bool:
        try:
            content = orch._get_pane_content()
        except Exception:
            logger.debug(
                'Unable to capture pane content during kill escalation',
                exc_info=True,
            )
            return False
        return content.rstrip().endswith(CMD_OUTPUT_PS1_END.rstrip())

    # Stage 1: SIGINT (Ctrl+C)
    logger.info('Kill escalation stage 1: sending SIGINT (C-c)')
    pane.send_keys('C-c', enter=False)
    time.sleep(2)

    if _prompt_returned():
        logger.info('Process terminated after SIGINT')
        return

    # Stage 2: SIGQUIT (Ctrl+\)
    logger.info('Kill escalation stage 2: sending SIGQUIT (C-\\)')
    pane.send_keys('C-\\', enter=False)
    time.sleep(1)

    if _prompt_returned():
        logger.info('Process terminated after SIGQUIT')
        return

    # Stage 3: kill the foreground process group
    logger.warning('Kill escalation stage 3: sending kill -9 to foreground pgroup')
    pane.send_keys('C-c', enter=False)
    time.sleep(0.3)
    # Send kill to the foreground job's process group
    pane.send_keys('kill -9 %1 2>/dev/null; true', enter=True)
    time.sleep(1)
    logger.info('Kill escalation complete')


def _handle_completed_command(
    orch: BashSession,
    command: str,
    pane_content: str,
    ps1_matches: list[Ps1Match],
    hidden: bool,
    is_input: bool = False,
) -> CmdOutputObservation:
    from backend.execution.utils.shell.bash import BashCommandStatus

    is_special_key = orch._is_special_key(command)
    assert ps1_matches, (
        'Expected at least one PS1 metadata block, but got '
        f'{len(ps1_matches)}.\n---FULL OUTPUT---\n{pane_content!r}'
        '\n---END OF OUTPUT---'
    )
    metadata = CmdOutputMetadata.from_ps1_match(ps1_matches[-1])
    get_content_before_last_match = len(ps1_matches) == 1
    if metadata.working_dir != orch._cwd and metadata.working_dir:
        orch._update_cwd(metadata.working_dir)
    logger.debug('COMMAND OUTPUT: %s', pane_content)
    raw_command_output = orch._combine_outputs_between_matches(
        pane_content,
        ps1_matches,
        get_content_before_last_match=get_content_before_last_match,
    )
    if get_content_before_last_match:
        num_lines = len(raw_command_output.splitlines())
        metadata.prefix = f'[Previous command outputs are truncated. Showing the last {num_lines} lines of the output below.]\n'
    metadata.suffix = (
        f'\n[The command completed with exit code {metadata.exit_code}. CTRL+{command[-1].upper()} was sent.]'
        if is_special_key
        else f'\n[The command completed with exit code {metadata.exit_code}.]'
    )
    if is_input and command != '':
        continue_prefix = ''
    else:
        continue_prefix = (
            '[Below is the output of the previous command.]\n'
            if orch.prev_output
            else ''
        )
    command_output = orch._get_command_output(
        command,
        raw_command_output,
        metadata,
        continue_prefix=continue_prefix,
    )
    orch.prev_status = BashCommandStatus.COMPLETED
    orch.prev_output = ''
    orch._ready_for_next_command()
    return CmdOutputObservation(
        content=command_output, command=command, metadata=metadata, hidden=hidden
    )


def _handle_nochange_timeout_command(
    orch: BashSession,
    command: str,
    pane_content: str,
    ps1_matches: list[Ps1Match],
) -> CmdOutputObservation:
    from backend.execution.utils.shell.bash import BashCommandStatus

    orch.prev_status = BashCommandStatus.NO_CHANGE_TIMEOUT
    if len(ps1_matches) != 1:
        logger.warning(
            'Expected exactly one PS1 metadata block BEFORE the execution of a command, but got %s PS1 metadata blocks:\n---\n%s\n---',
            len(ps1_matches),
            pane_content,
        )
    raw_command_output = orch._combine_outputs_between_matches(
        pane_content, ps1_matches
    )
    metadata = CmdOutputMetadata()
    command_output = orch._get_command_output(
        command,
        raw_command_output,
        metadata,
        continue_prefix='[Below is the output of the previous command.]\n',
    )

    bg_id = orch._pending_bg_id
    if bg_id is not None:
        # Try to detach the running process to a background session so the
        # agent can poll it with terminal_read() instead of losing output.
        try:
            orch._detach_pane_to_background(bg_id)
            metadata.suffix = (
                f'\n[The command has no new output after {orch.NO_CHANGE_TIMEOUT_SECONDS} seconds. '
                f'It is still running in background session "{bg_id}". '
                f'Use terminal_read(session_id="{bg_id}") to poll for new output, '
                f'or terminal_read(session_id="{bg_id}", mode="snapshot") for the full buffer. '
                f'When the command completes, the session will show the shell prompt.]'
            )
            logger.info(
                'No-change timeout: moved command to background session %s', bg_id
            )
        except Exception:
            logger.warning(
                'Background detach failed for session %s, killing process instead',
                bg_id,
                exc_info=True,
            )
            orch._bg_session_id = None
            orch._detached_pane = None
            orch._detached_window = None
            metadata.suffix = f'\n[The command has no new output after {orch.NO_CHANGE_TIMEOUT_SECONDS} seconds. {TIMEOUT_MESSAGE_TEMPLATE}]'
            _kill_hung_process(orch)
    else:
        # No background-detach requested: kill and free the pane (original behavior).
        metadata.suffix = f'\n[The command has no new output after {orch.NO_CHANGE_TIMEOUT_SECONDS} seconds. {TIMEOUT_MESSAGE_TEMPLATE}]'
        _kill_hung_process(orch)

    return CmdOutputObservation(
        content=command_output, command=command, metadata=metadata
    )


def _handle_hard_timeout_command(
    orch: BashSession,
    command: str,
    pane_content: str,
    ps1_matches: list[Ps1Match],
    timeout: float,
) -> CmdOutputObservation:
    from backend.execution.utils.shell.bash import BashCommandStatus

    orch.prev_status = BashCommandStatus.HARD_TIMEOUT
    if len(ps1_matches) != 1:
        logger.warning(
            'Expected exactly one PS1 metadata block BEFORE the execution of a command, but got %s PS1 metadata blocks:\n---\n%s\n---',
            len(ps1_matches),
            pane_content,
        )
    raw_command_output = orch._combine_outputs_between_matches(
        pane_content, ps1_matches
    )
    metadata = CmdOutputMetadata()
    metadata.suffix = (
        f'\n[The command timed out after {timeout} seconds. {TIMEOUT_MESSAGE_TEMPLATE}]'
    )
    command_output = orch._get_command_output(
        command,
        raw_command_output,
        metadata,
        continue_prefix='[Below is the output of the previous command.]\n',
    )

    # Kill the hung process so the tmux pane is freed for the next command.
    _kill_hung_process(orch)

    return CmdOutputObservation(
        command=command, content=command_output, metadata=metadata
    )


def _handle_previous_command_timeout(
    orch: BashSession,
    command: str,
    last_pane_output: str,
    initial_ps1_matches: list[Ps1Match],
    is_input: bool,
) -> CmdOutputObservation | None:
    """Handle case where previous command timed out."""
    from backend.execution.utils.shell.bash import BashCommandStatus

    if (
        orch.prev_status
        in {BashCommandStatus.HARD_TIMEOUT, BashCommandStatus.NO_CHANGE_TIMEOUT}
        and not last_pane_output.rstrip().endswith(CMD_OUTPUT_PS1_END.rstrip())
        and not is_input
        and command != ''
    ):
        _ps1_matches = _match_ps1(last_pane_output)
        current_matches_for_output = _ps1_matches or initial_ps1_matches
        raw_command_output = orch._combine_outputs_between_matches(
            last_pane_output, current_matches_for_output
        )
        metadata = CmdOutputMetadata()
        metadata.suffix = f'\n[Your command "{command}" is NOT executed. The previous command is still running - You CANNOT send new commands until the previous command is completed. By setting `is_input` to `true`, you can interact with the current process: {TIMEOUT_MESSAGE_TEMPLATE}]'
        logger.debug('PREVIOUS COMMAND OUTPUT: %s', raw_command_output)
        command_output = orch._get_command_output(
            command,
            raw_command_output,
            metadata,
            continue_prefix='[Below is the output of the previous command.]\n',
        )
        return CmdOutputObservation(
            command=command,
            content=command_output,
            metadata=metadata,
            hidden=False,
        )
    return None


def _check_timeouts(
    orch: BashSession,
    action: CmdRunAction,
    last_change_time: float,
    start_time: float,
    command: str,
    cur_pane_output: str,
    ps1_matches: list[Ps1Match],
    first_output_seen: bool = True,
) -> CmdOutputObservation | None:
    """Check for various timeout conditions.

    Idle-output timeout fires for ALL commands (blocking or not).
    Blocking commands get a longer idle threshold (2×) to accommodate
    slow builds/installs that produce periodic output.

    Before the FIRST output is observed (``first_output_seen=False``),
    the idle threshold is doubled to give slow-start commands such as
    ``npm install`` or ``pip install`` time to complete network setup.
    """
    time_since_last_change = time.time() - last_change_time

    # Idle timeout: fires for ALL commands.  Blocking commands get a
    # longer grace period (2×) since builds/installs may have long
    # quiet phases (e.g. linking, compressing).
    idle_threshold = (
        orch.NO_CHANGE_TIMEOUT_SECONDS * 2
        if action.blocking
        else orch.NO_CHANGE_TIMEOUT_SECONDS
    )
    # T-P0-1: extend the FIRST idle window so commands that download
    # metadata before printing don't get prematurely detached.
    if not first_output_seen:
        idle_threshold *= 2
    logger.debug(
        'CHECKING NO CHANGE TIMEOUT (%ss): elapsed %s. Action blocking: %s',
        idle_threshold,
        time_since_last_change,
        action.blocking,
    )

    if time_since_last_change >= idle_threshold:
        return _handle_nochange_timeout_command(
            orch, command, pane_content=cur_pane_output, ps1_matches=ps1_matches
        )

    # Hard timeout: always enforced.  If the action has no explicit
    # timeout we fall back to _SAFETY_NET_TIMEOUT (600s) to prevent
    # truly pathological hangs.
    from backend.execution.runtime_mixins.command_timeout import SAFETY_NET_TIMEOUT

    effective_timeout = (
        min(action.timeout, SAFETY_NET_TIMEOUT)
        if action.timeout is not None
        else SAFETY_NET_TIMEOUT
    )

    elapsed_time = time.time() - start_time
    logger.debug(
        'CHECKING HARD TIMEOUT (%ss): elapsed %s', effective_timeout, elapsed_time
    )

    if elapsed_time >= effective_timeout:
        logger.debug('Hard timeout triggered.')
        return _handle_hard_timeout_command(
            orch,
            command,
            pane_content=cur_pane_output,
            ps1_matches=ps1_matches,
            timeout=effective_timeout,
        )

    return None


def _monitor_command_execution(
    orch: BashSession,
    command: str,
    initial_ps1_count: int,
    is_input: bool,
    action: CmdRunAction,
    initial_pane_output: str | None = None,
) -> CmdOutputObservation:
    """Monitor command execution until completion or timeout."""
    start_time = time.time()
    last_change_time = start_time
    last_pane_output = orch._get_pane_content()
    # Baseline used to detect the FIRST output produced by *this* command.
    # Falls back to the post-send pane content if the caller didn't pass
    # the pre-send snapshot (preserves legacy callers).
    baseline_pane_output = (
        initial_pane_output if initial_pane_output is not None else last_pane_output
    )
    first_output_seen = last_pane_output != baseline_pane_output

    while should_continue():
        _start_time = time.time()
        logger.debug('GETTING PANE CONTENT at %s', _start_time)
        cur_pane_output = orch._get_pane_content()
        ps1_matches = _match_ps1(cur_pane_output)
        logger.debug('PANE CONTENT GOT after %s seconds', time.time() - _start_time)
        logger.debug('BEGIN OF PANE CONTENT: %s', cur_pane_output.split('\n')[:10])
        logger.debug('END OF PANE CONTENT: %s', cur_pane_output.split('\n')[-10:])

        if cur_pane_output != last_pane_output:
            last_pane_output = cur_pane_output
            last_change_time = time.time()
            if cur_pane_output != baseline_pane_output:
                first_output_seen = True
            logger.debug('CONTENT UPDATED DETECTED at %s', last_change_time)

            # Check for interactive prompts and auto-respond
            if orch._handle_interactive_prompts(cur_pane_output, is_input):
                # Reset last_change_time to avoid timeout during prompt handling
                last_change_time = time.time()
                continue

            # Check for server startup
            orch._detect_server_startup(cur_pane_output)

        if completion_result := orch._check_command_completion(
            cur_pane_output,
            ps1_matches,
            initial_ps1_count,
            command,
            is_input,
        ):
            return completion_result

        if timeout_result := _check_timeouts(
            orch,
            action,
            last_change_time,
            start_time,
            command,
            cur_pane_output,
            ps1_matches,
            first_output_seen=first_output_seen,
        ):
            return timeout_result

        logger.debug('SLEEPING for %s seconds for next poll', orch.POLL_INTERVAL)
        time.sleep(orch.POLL_INTERVAL)

    msg = 'Bash session was likely interrupted...'
    raise RuntimeError(msg)
