"""Utilities for executing and monitoring bash commands within runtime sessions."""

from __future__ import annotations

import getpass
import os
import re
import time
import traceback
import uuid
from enum import Enum
from typing import TYPE_CHECKING, Any, cast

import bashlex
import libtmux

from backend.core.logger import forge_logger as logger
from backend.events.observation import ErrorObservation
from backend.events.observation.commands import (
    CMD_OUTPUT_PS1_END,
    CmdOutputMetadata,
    CmdOutputObservation,
)
from backend.runtime.utils.bash_constants import TIMEOUT_MESSAGE_TEMPLATE
from backend.runtime.utils.prompt_detector import detect_interactive_prompt
from backend.utils.shutdown_listener import should_continue

from backend.runtime.utils.unified_shell import BaseShellSession

if TYPE_CHECKING:
    from libtmux.pane import Pane
    from libtmux.server import Server
    from libtmux.session import Session
    from libtmux.window import Window

    from backend.events.action import CmdRunAction
    from backend.runtime.utils.process_registry import TaskCancellationService


def split_bash_commands(commands: str) -> list[str]:
    """Split bash commands string into individual commands.

    Args:
        commands: String containing multiple bash commands.

    Returns:
        list[str]: List of individual bash commands.

    """
    if not commands.strip():
        return [""]
    try:
        parsed = bashlex.parse(commands)
    except (
        bashlex.errors.ParsingError,
        NotImplementedError,
        TypeError,
        AttributeError,
    ):
        logger.debug(
            "Failed to parse bash commands\n[input]: %s\n[warning]: %s\nThe original command will be returned as is.",
            commands,
            traceback.format_exc(),
        )
        return [commands]
    result: list[str] = []
    last_end = 0
    for node in parsed:
        start, end = node.pos
        if start > last_end:
            between = commands[last_end:start]
            logger.debug("BASH PARSING between: %s", between)
            if result:
                result[-1] += between.rstrip()
            elif between.strip():
                result.append(between.rstrip())
        command = commands[start:end].rstrip()
        logger.debug("BASH PARSING command: %s", command)
        result.append(command)
        last_end = end
    remaining = commands[last_end:].rstrip()
    logger.debug("BASH PARSING remaining: %s", remaining)
    if last_end < len(commands):
        if result:
            result[-1] += remaining
            logger.debug("BASH PARSING result[-1] += remaining: %s", result[-1])
        elif remaining:
            result.append(remaining)
            logger.debug("BASH PARSING result.append(remaining): %s", result[-1])
    return result


def escape_bash_special_chars(command: str) -> str:
    r"""Escapes characters that have different interpretations in bash vs python.

    Specifically handles escape sequences like \\;, \\|, \\&, etc.
    """
    if not command.strip():
        return ""
    try:
        parts = []
        last_pos = 0

        def visit_node(node: Any) -> None:
            """Visit AST node to extract heredoc content.

            Args:
                node: AST node to visit

            """
            nonlocal last_pos
            if (
                node.kind == "redirect"
                and hasattr(node, "heredoc")
                and (node.heredoc is not None)
            ):
                between = command[last_pos : node.pos[0]]
                parts.append(between)
                parts.append(command[node.pos[0] : node.heredoc.pos[0]])
                parts.append(command[node.heredoc.pos[0] : node.heredoc.pos[1]])
                last_pos = node.pos[1]
                return
            if node.kind == "word":
                between = command[last_pos : node.pos[0]]
                word_text = command[node.pos[0] : node.pos[1]]
                between = re.sub("\\\\([;&|><])", "\\\\\\\\\\1", between)
                parts.append(between)
                if (
                    (word_text.startswith('"') and word_text.endswith('"'))
                    or (word_text.startswith("'") and word_text.endswith("'"))
                    or (word_text.startswith("$(") and word_text.endswith(")"))
                    or (word_text.startswith("`") and word_text.endswith("`"))
                ):
                    parts.append(word_text)
                else:
                    word_text = re.sub("\\\\([;&|><])", "\\\\\\\\\\1", word_text)
                    parts.append(word_text)
                last_pos = node.pos[1]
                return
            if hasattr(node, "parts"):
                for part in node.parts:
                    visit_node(part)

        nodes = list(bashlex.parse(command))
        for node in nodes:
            between = command[last_pos : node.pos[0]]
            between = re.sub("\\\\([;&|><])", "\\\\\\\\\\1", between)
            parts.append(between)
            last_pos = node.pos[0]
            visit_node(node)
        remaining = command[last_pos:]
        parts.append(remaining)
        return "".join(parts)
    except (bashlex.errors.ParsingError, NotImplementedError, TypeError):
        logger.debug(
            "Failed to parse bash commands for special characters escape\n[input]: %s\n[warning]: %s\nThe original command will be returned as is.",
            command,
            traceback.format_exc(),
        )
        return command


class BashCommandStatus(Enum):
    """State machine statuses emitted while monitoring bash command execution."""

    CONTINUE = "continue"
    COMPLETED = "completed"
    NO_CHANGE_TIMEOUT = "no_change_timeout"
    HARD_TIMEOUT = "hard_timeout"


def _remove_command_prefix(command_output: str, command: str) -> str:
    """Remove command prefix from command output.

    Args:
        command_output: The output string from the command.
        command: The original command that was executed.

    Returns:
        str: The output with the command prefix removed.

    """
    return command_output.lstrip().removeprefix(command.lstrip()).lstrip()


class BashSession(BaseShellSession):
    """Manage a tmux-backed bash session for running agent commands."""

    POLL_INTERVAL = 0.5
    HISTORY_LIMIT = 10000
    PS1 = CmdOutputMetadata.to_ps1_prompt()

    def __init__(
        self,
        work_dir: str,
        username: str | None = None,
        no_change_timeout_seconds: int = 30,
        max_memory_mb: int | None = None,
        cancellation_service: TaskCancellationService | None = None,
    ) -> None:
        """Configure tmux-backed shell session defaults and resource limits."""
        super().__init__(
            work_dir=work_dir,
            username=username,
            no_change_timeout_seconds=no_change_timeout_seconds,
            max_memory_mb=max_memory_mb,
            cancellation_service=cancellation_service,
        )
        self._cancellation_callback_key: str | None = None
        self.server: Server | None = None
        self.session: Session | None = None
        self.window: Window | None = None
        self.pane: Pane | None = None
        self.prev_status: BashCommandStatus | None = None
        self.prev_output: str = ""

    def initialize(self) -> None:
        """Initialize tmux server and session for bash runtime."""
        self._prepare_tmux_tmpdir()
        try:
            server = libtmux.Server()
        except Exception as exc:
            raise RuntimeError(
                "Failed to initialize tmux server. Ensure tmux is installed and "
                "TMUX_TMPDIR is writable in this runtime."
            ) from exc
        self.server = server
        _shell_command = "/bin/bash"
        if self._should_use_su():
            _shell_command = f"su {self.username} -"
        window_command = _shell_command
        logger.debug("Initializing bash session with command: %s", window_command)
        session_name = f"Forge-{self.username}-{uuid.uuid4()}"
        session_obj = cast(Any, server).new_session(
            session_name=session_name,
            start_directory=self.work_dir,
            kill_session=True,
            attach=False,
            window_name="bash",
            window_command=window_command,
            x=1000,
            y=1000,
        )
        if session_obj is None:
            raise RuntimeError("Failed to create tmux session")
        session = cast("Session", session_obj)
        self.session = session

        # Register a session-scoped kill callback so runtime.hard_kill() can
        # terminate this tmux session (and its process tree) reliably.
        if self._cancellation is not None:
            self._cancellation_callback_key = f"tmux-session:{session_name}"
            self._cancellation.register_kill_callback(
                self._cancellation_callback_key,
                self._hard_kill_tmux_session,
            )
        session.set_option("history-limit", str(self.HISTORY_LIMIT), _global=True)
        session.history_limit = str(self.HISTORY_LIMIT)
        window, pane = self._get_window_and_pane_with_retry(session)
        self.window = window
        self.pane = pane
        logger.debug("pane: %s; history_limit: %s", pane, session.history_limit)
        pane.send_keys(
            f'''export PROMPT_COMMAND='export PS1="{self.PS1}"'; export PS2=""'''
        )
        time.sleep(0.1)
        self._clear_screen()
        logger.debug("Bash session initialized with work dir: %s", self.work_dir)
        self._cwd = os.path.abspath(self.work_dir)
        self._initialized = True

    def _prepare_tmux_tmpdir(self) -> None:
        """Validate and prepare TMUX_TMPDIR when explicitly configured."""
        tmpdir = os.environ.get("TMUX_TMPDIR", "").strip()
        if not tmpdir:
            return
        try:
            os.makedirs(tmpdir, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(
                f"TMUX_TMPDIR '{tmpdir}' could not be created"
            ) from exc
        if not os.access(tmpdir, os.W_OK):
            raise RuntimeError(f"TMUX_TMPDIR '{tmpdir}' is not writable")

    def _hard_kill_tmux_session(self) -> None:
        session = self.session
        if session is None:
            return
        try:
            session.kill()
        except Exception:
            logger.debug("Failed to kill tmux session", exc_info=True)

    def _should_use_su(self) -> bool:
        """Determine if we should wrap shell command in `su username -`."""
        username = self.username
        if not username:
            return False
        if not hasattr(os, "geteuid"):
            return False
        try:
            uid = int(os.geteuid())
        except AttributeError:
            return False
        if uid != 0:
            return False
        current_user = None
        try:
            current_user = getpass.getuser()
        except Exception:
            logger.debug("Unable to determine current user for bash session")
        return current_user != username

    def _update_cwd(self, output: str) -> None:
        """Update current working directory from command output.

        Args:
            output: Command output containing potential CWD information
        """
        self._cwd = output

    def close(self) -> None:
        """Clean up the session."""
        if self._closed:
            return
        logger.info("Closing BashSession...")
        if self._cancellation is not None and self._cancellation_callback_key:
            try:
                self._cancellation.unregister_kill_callback(
                    self._cancellation_callback_key
                )
            except Exception:
                logger.debug("Failed to unregister tmux kill callback", exc_info=True)
        session = self.session
        if session is not None:
            try:
                session.kill()
            except Exception:
                logger.debug("Failed to kill tmux session during close", exc_info=True)
        super().close()
        self._initialized = False
        logger.info("BashSession closed")

    @property
    def cwd(self) -> str:
        """Get current working directory for bash runtime."""
        return self._cwd

    def _get_pane_content(self) -> str:
        """Capture the current pane content and update the buffer."""
        pane = self._require_pane()
        return "\n".join(
            line.rstrip() for line in pane.cmd("capture-pane", "-J", "-pS", "-").stdout
        )

    def _get_window_and_pane_with_retry(
        self, session: Session, retries: int = 10, delay: float = 0.1
    ) -> tuple[Window, Pane]:
        """Fetch the active tmux window and pane, retrying if tmux is still booting."""
        last_exc: Exception | None = None
        for attempt in range(retries):
            window = cast("Window | None", getattr(session, "active_window", None))
            if window is None:
                time.sleep(delay)
                continue
            try:
                pane = cast("Pane | None", getattr(window, "active_pane", None))
            except libtmux.exc.LibTmuxException as exc:  # type: ignore[attr-defined]
                last_exc = exc
                logger.debug(
                    "Active pane lookup failed on attempt %s/%s: %s",
                    attempt + 1,
                    retries,
                    exc,
                )
                time.sleep(delay)
                continue
            if pane is not None:
                return window, pane
            time.sleep(delay)
        raise RuntimeError("Window has no active pane") from last_exc

    def _require_pane(self) -> Pane:
        pane = self.pane
        if pane is None:
            raise RuntimeError("Bash session pane is not initialized")
        return pane

    def _is_special_key(self, command: str) -> bool:
        """Check if the command is a special key."""
        _command = command.strip()
        return _command.startswith("C-") and len(_command) == 3

    def _clear_screen(self) -> None:
        """Clear the tmux pane screen and history."""
        pane = self._require_pane()
        pane.send_keys("C-l", enter=False)
        time.sleep(0.1)
        pane.cmd("clear-history")

    def _get_command_output(
        self,
        command: str,
        raw_command_output: str,
        metadata: CmdOutputMetadata,
        continue_prefix: str = "",
    ) -> str:
        """Get the command output with the previous command output removed.

        Args:
            command: The command that was executed.
            raw_command_output: The raw output from the command.
            metadata: The metadata object to store prefix/suffix in.
            continue_prefix: The prefix to add to the command output if it's a continuation of the previous command.

        """
        if self.prev_output:
            command_output = raw_command_output.removeprefix(self.prev_output)
            metadata.prefix = continue_prefix
        else:
            command_output = raw_command_output
        self.prev_output = raw_command_output
        command_output = _remove_command_prefix(command_output, command)
        return command_output.rstrip()

    def _handle_completed_command(
        self,
        command: str,
        pane_content: str,
        ps1_matches: list[re.Match],
        hidden: bool,
        is_input: bool = False,
    ) -> CmdOutputObservation:
        is_special_key = self._is_special_key(command)
        assert ps1_matches, f"Expected at least one PS1 metadata block, but got {
            len(ps1_matches)
        }.\n---FULL OUTPUT---\n{pane_content!r}\n---END OF OUTPUT---"
        metadata = CmdOutputMetadata.from_ps1_match(ps1_matches[-1])
        get_content_before_last_match = len(ps1_matches) == 1
        if metadata.working_dir != self._cwd and metadata.working_dir:
            self._update_cwd(metadata.working_dir)
        logger.debug("COMMAND OUTPUT: %s", pane_content)
        raw_command_output = self._combine_outputs_between_matches(
            pane_content,
            ps1_matches,
            get_content_before_last_match=get_content_before_last_match,
        )
        if get_content_before_last_match:
            num_lines = len(raw_command_output.splitlines())
            metadata.prefix = f"[Previous command outputs are truncated. Showing the last {num_lines} lines of the output below.]\n"
        metadata.suffix = (
            f"\n[The command completed with exit code {metadata.exit_code}. CTRL+{command[-1].upper()} was sent.]"
            if is_special_key
            else f"\n[The command completed with exit code {metadata.exit_code}.]"
        )
        if is_input and command != "":
            continue_prefix = ""
        else:
            continue_prefix = (
                "[Below is the output of the previous command.]\n"
                if self.prev_output
                else ""
            )
        command_output = self._get_command_output(
            command,
            raw_command_output,
            metadata,
            continue_prefix=continue_prefix,
        )
        self.prev_status = BashCommandStatus.COMPLETED
        self.prev_output = ""
        self._ready_for_next_command()
        return CmdOutputObservation(
            content=command_output, command=command, metadata=metadata, hidden=hidden
        )

    def _handle_nochange_timeout_command(
        self,
        command: str,
        pane_content: str,
        ps1_matches: list[re.Match],
    ) -> CmdOutputObservation:
        self.prev_status = BashCommandStatus.NO_CHANGE_TIMEOUT
        if len(ps1_matches) != 1:
            logger.warning(
                "Expected exactly one PS1 metadata block BEFORE the execution of a command, but got %s PS1 metadata blocks:\n---\n%s\n---",
                len(ps1_matches),
                pane_content,
            )
        raw_command_output = self._combine_outputs_between_matches(
            pane_content, ps1_matches
        )
        metadata = CmdOutputMetadata()
        metadata.suffix = f"\n[The command has no new output after {
            self.NO_CHANGE_TIMEOUT_SECONDS
        } seconds. {TIMEOUT_MESSAGE_TEMPLATE}]"
        command_output = self._get_command_output(
            command,
            raw_command_output,
            metadata,
            continue_prefix="[Below is the output of the previous command.]\n",
        )
        return CmdOutputObservation(
            content=command_output, command=command, metadata=metadata
        )

    def _handle_hard_timeout_command(
        self,
        command: str,
        pane_content: str,
        ps1_matches: list[re.Match],
        timeout: float,
    ) -> CmdOutputObservation:
        self.prev_status = BashCommandStatus.HARD_TIMEOUT
        if len(ps1_matches) != 1:
            logger.warning(
                "Expected exactly one PS1 metadata block BEFORE the execution of a command, but got %s PS1 metadata blocks:\n---\n%s\n---",
                len(ps1_matches),
                pane_content,
            )
        raw_command_output = self._combine_outputs_between_matches(
            pane_content, ps1_matches
        )
        metadata = CmdOutputMetadata()
        metadata.suffix = f"\n[The command timed out after {timeout} seconds. {TIMEOUT_MESSAGE_TEMPLATE}]"
        command_output = self._get_command_output(
            command,
            raw_command_output,
            metadata,
            continue_prefix="[Below is the output of the previous command.]\n",
        )
        return CmdOutputObservation(
            command=command, content=command_output, metadata=metadata
        )

    def _ready_for_next_command(self) -> None:
        """Reset the content buffer for a new command."""
        self._clear_screen()

    def _combine_outputs_between_matches(
        self,
        pane_content: str,
        ps1_matches: list[re.Match],
        get_content_before_last_match: bool = False,
    ) -> str:
        """Combine all outputs between PS1 matches.

        Args:
            pane_content: The full pane content containing PS1 prompts and command outputs
            ps1_matches: List of regex matches for PS1 prompts
            get_content_before_last_match: when there's only one PS1 match, whether to get
                the content before the last PS1 prompt (True) or after the last PS1 prompt (False)

        Returns:
            Combined string of all outputs between matches

        """
        if len(ps1_matches) == 1:
            if get_content_before_last_match:
                return pane_content[: ps1_matches[0].start()]
            return pane_content[ps1_matches[0].end() + 1 :]
        if not ps1_matches:
            return pane_content
        combined_output = ""
        for i in range(len(ps1_matches) - 1):
            output_segment = pane_content[
                ps1_matches[i].end() + 1 : ps1_matches[i + 1].start()
            ]
            combined_output += output_segment + "\n"
        combined_output += pane_content[ps1_matches[-1].end() + 1 :]
        logger.debug("COMBINED OUTPUT: %s", combined_output)
        return combined_output

    def _validate_session_and_command(self, action: CmdRunAction) -> None:
        """Validate session is initialized and command is valid."""
        if not self._initialized:
            msg = "Bash session is not initialized"
            raise RuntimeError(msg)

        logger.debug("RECEIVED ACTION: %s", action)

        command = action.command.strip()
        if self.prev_status not in {
            BashCommandStatus.CONTINUE,
            BashCommandStatus.NO_CHANGE_TIMEOUT,
            BashCommandStatus.HARD_TIMEOUT,
        }:
            if command == "":
                msg = "ERROR: No previous running command to retrieve logs from."
                raise ValueError(msg)
            is_input: bool = action.is_input

            if is_input:
                msg = "ERROR: No previous running command to interact with."
                raise ValueError(msg)

        splited_commands = split_bash_commands(command)
        if len(splited_commands) > 1:
            msg = f"ERROR: Cannot execute multiple commands at once.\nPlease run each command separately OR chain them into a single command via && or ;\nProvided commands:\n{
                '\n'.join(
                    (f'({i + 1}) {cmd}' for i, cmd in enumerate(splited_commands))
                )
            }"
            raise ValueError(
                msg,
            )

    def _handle_previous_command_timeout(
        self,
        command: str,
        last_pane_output: str,
        initial_ps1_matches: list,
        is_input: bool,
    ) -> CmdOutputObservation | None:
        """Handle case where previous command timed out."""
        if (
            self.prev_status
            in {BashCommandStatus.HARD_TIMEOUT, BashCommandStatus.NO_CHANGE_TIMEOUT}
            and not last_pane_output.rstrip().endswith(CMD_OUTPUT_PS1_END.rstrip())
            and not is_input
            and command != ""
        ):
            _ps1_matches = CmdOutputMetadata.matches_ps1_metadata(last_pane_output)
            current_matches_for_output = _ps1_matches or initial_ps1_matches
            raw_command_output = self._combine_outputs_between_matches(
                last_pane_output, current_matches_for_output
            )
            metadata = CmdOutputMetadata()
            metadata.suffix = f'\n[Your command "{command}" is NOT executed. The previous command is still running - You CANNOT send new commands until the previous command is completed. By setting `is_input` to `true`, you can interact with the current process: {TIMEOUT_MESSAGE_TEMPLATE}]'
            logger.debug("PREVIOUS COMMAND OUTPUT: %s", raw_command_output)
            command_output = self._get_command_output(
                command,
                raw_command_output,
                metadata,
                continue_prefix="[Below is the output of the previous command.]\n",
            )
            return CmdOutputObservation(
                command=command,
                content=command_output,
                metadata=metadata,
                hidden=False,
            )
        return None

    def _send_command_to_pane(self, command: str, is_input: bool) -> None:
        """Send command or input to the pane."""
        pane = self._require_pane()
        if is_input:
            is_special_key = self._is_special_key(command)
            logger.debug("SENDING INPUT TO RUNNING PROCESS: %s", command)
            pane.send_keys(command, enter=not is_special_key)
        elif command != "":
            is_special_key = self._is_special_key(command)
            command = escape_bash_special_chars(command)
            logger.debug("SENDING COMMAND: %s", command)
            pane.send_keys(command, enter=not is_special_key)

    def _check_command_completion(
        self,
        cur_pane_output: str,
        ps1_matches: list,
        initial_ps1_count: int,
        command: str,
        is_input: bool,
    ) -> CmdOutputObservation | None:
        """Check if command has completed and return observation if so."""
        current_ps1_count = len(ps1_matches)
        if current_ps1_count > initial_ps1_count or cur_pane_output.rstrip().endswith(
            CMD_OUTPUT_PS1_END.rstrip()
        ):
            return self._handle_completed_command(
                command,
                pane_content=cur_pane_output,
                ps1_matches=ps1_matches,
                hidden=False,
                is_input=is_input,
            )
        return None

    def _check_timeouts(
        self,
        action: CmdRunAction,
        last_change_time: float,
        start_time: float,
        command: str,
        cur_pane_output: str,
        ps1_matches: list,
    ) -> CmdOutputObservation | None:
        """Check for various timeout conditions."""
        time_since_last_change = time.time() - last_change_time
        logger.debug(
            "CHECKING NO CHANGE TIMEOUT (%ss): elapsed %s. Action blocking: %s",
            self.NO_CHANGE_TIMEOUT_SECONDS,
            time_since_last_change,
            action.blocking,
        )

        if (
            not action.blocking
            and time_since_last_change >= self.NO_CHANGE_TIMEOUT_SECONDS
        ):
            return self._handle_nochange_timeout_command(
                command, pane_content=cur_pane_output, ps1_matches=ps1_matches
            )

        # Skip hard timeout check if timeout is None (long-running commands like servers)
        if action.timeout is None:
            logger.debug(
                "No hard timeout set (long-running command), skipping timeout check"
            )
            return None

        elapsed_time = time.time() - start_time
        logger.debug(
            "CHECKING HARD TIMEOUT (%ss): elapsed %s", action.timeout, elapsed_time
        )

        if action.timeout and elapsed_time >= action.timeout:
            logger.debug("Hard timeout triggered.")
            return self._handle_hard_timeout_command(
                command,
                pane_content=cur_pane_output,
                ps1_matches=ps1_matches,
                timeout=action.timeout,
            )

        return None

    def _monitor_command_execution(
        self,
        command: str,
        initial_ps1_count: int,
        is_input: bool,
        action: CmdRunAction,
    ) -> CmdOutputObservation:
        """Monitor command execution until completion or timeout."""
        start_time = time.time()
        last_change_time = start_time
        last_pane_output = self._get_pane_content()

        while should_continue():
            _start_time = time.time()
            logger.debug("GETTING PANE CONTENT at %s", _start_time)
            cur_pane_output = self._get_pane_content()
            logger.debug("PANE CONTENT GOT after %s seconds", time.time() - _start_time)
            logger.debug("BEGIN OF PANE CONTENT: %s", cur_pane_output.split("\n")[:10])
            logger.debug("END OF PANE CONTENT: %s", cur_pane_output.split("\n")[-10:])

            ps1_matches = CmdOutputMetadata.matches_ps1_metadata(cur_pane_output)

            if cur_pane_output != last_pane_output:
                last_pane_output = cur_pane_output
                last_change_time = time.time()
                logger.debug("CONTENT UPDATED DETECTED at %s", last_change_time)

                # Check for interactive prompts and auto-respond
                if self._handle_interactive_prompts(cur_pane_output, is_input):
                    # Reset last_change_time to avoid timeout during prompt handling
                    last_change_time = time.time()
                    continue

                # Check for server startup
                self._detect_server_startup(cur_pane_output)

            if completion_result := self._check_command_completion(
                cur_pane_output,
                ps1_matches,
                initial_ps1_count,
                command,
                is_input,
            ):
                return completion_result

            if timeout_result := self._check_timeouts(
                action,
                last_change_time,
                start_time,
                command,
                cur_pane_output,
                ps1_matches,
            ):
                return timeout_result

            logger.debug("SLEEPING for %s seconds for next poll", self.POLL_INTERVAL)
            time.sleep(self.POLL_INTERVAL)

        msg = "Bash session was likely interrupted..."
        raise RuntimeError(msg)

    def _handle_interactive_prompts(self, output: str, is_input: bool) -> bool:
        """Check for interactive prompts and respond if detected."""
        is_prompt, response = detect_interactive_prompt(output)
        if is_prompt and response:
            logger.info(
                "🤖 Auto-responding to interactive prompt with: %r",
                response,
            )
            self._send_command_to_pane(response, is_input=True)
            # Give the system time to process the input
            time.sleep(0.2)
            return True
        return False

    def _detect_server_startup(self, output: str) -> None:
        """Check for server startup in command output."""
        from backend.runtime.utils.server_detector import detect_server_from_output

        detected_server = detect_server_from_output(output, perform_health_check=True)
        if detected_server and not hasattr(self, "_last_detected_server_url"):
            logger.info(
                "🚀 Server detected: %s (health: %s)",
                detected_server.url,
                detected_server.health_status,
            )
            # Store for runtime to emit ServerReadyObservation - only detect each server once
            self._last_detected_server = detected_server
            self._last_detected_server_url = detected_server.url

    def execute(self, action: CmdRunAction) -> CmdOutputObservation | ErrorObservation:
        """Execute a command in the bash session."""
        try:
            # Validate session and command
            self._validate_session_and_command(action)
        except ValueError as e:
            if "No previous running command" in str(e):
                return CmdOutputObservation(
                    content=str(e), command="", metadata=CmdOutputMetadata()
                )
            return ErrorObservation(content=str(e))

        command = action.command.strip()
        is_input: bool = action.is_input

        # Get initial state
        initial_pane_output = self._get_pane_content()
        initial_ps1_matches = CmdOutputMetadata.matches_ps1_metadata(
            initial_pane_output
        )
        initial_ps1_count = len(initial_ps1_matches)
        logger.debug("Initial PS1 count: %s", initial_ps1_count)

        if timeout_result := self._handle_previous_command_timeout(
            command,
            initial_pane_output,
            initial_ps1_matches,
            is_input,
        ):
            return timeout_result

        # Send command to pane
        self._send_command_to_pane(command, is_input)

        # Monitor execution
        return self._monitor_command_execution(
            command, initial_ps1_count, is_input, action
        )

    def get_detected_server(self):
        """Get and clear the last detected server.

        Returns:
            DetectedServer if one was detected since last check, None otherwise

        """
        if hasattr(self, "_last_detected_server"):
            server = self._last_detected_server
            # Clear for next detection
            del self._last_detected_server
            del self._last_detected_server_url
            return server
        return None

    def read_output(self) -> str:
        """Read pending output from the shell session."""
        try:
            return self._get_pane_content()
        except RuntimeError:
            return ""

    def write_input(self, data: str, is_control: bool = False) -> None:
        """Write input to the shell session."""
        pane = self._require_pane()
        if is_control:
            # For control sequences, send them directly (e.g. 'C-c')
            logger.debug("SENDING CONTROL INPUT: %s", data)
            pane.send_keys(data, enter=False)
        else:
            # For regular input, send as keys
            logger.debug("SENDING INPUT: %s", data)
            pane.send_keys(data, enter=True)
