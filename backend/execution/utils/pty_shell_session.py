"""Cross-platform interactive shell session backed by the PTY primitive.

This adapter plugs ``InteractiveSession`` (see ``pty_session.py``) into the
``UnifiedShellSession`` contract so existing executor / session-manager code
can transparently use a real interactive terminal on **any** OS, without
requiring tmux.

Typical use case: ``terminal_run`` / ``terminal_input`` / ``terminal_read``
actions in the executor.  Until now these were effectively no-ops on Windows
and on POSIX without tmux; this session implements them via ConPTY / forkpty
under the hood.

The class intentionally stays small: the hard parts (I/O pumping, buffer
management, exit-code capture, control sequences, resize) live in the
primitive. Here we only translate between the session-manager API and the
primitive's API.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import time
from typing import TYPE_CHECKING

from backend.core.logger import app_logger as logger
from backend.core.os_capabilities import OS_CAPS
from backend.execution.utils.pty_session import (
    CONTROL_SEQUENCES,
    InteractiveSession,
    InteractiveSessionConfig,
    InteractiveSessionError,
    PtyUnavailableError,
)
from backend.execution.utils.unified_shell import BaseShellSession
from backend.ledger.observation import ErrorObservation
from backend.ledger.observation.commands import (
    CmdOutputMetadata,
    CmdOutputObservation,
)

if TYPE_CHECKING:
    from backend.execution.utils.process_registry import TaskCancellationService
    from backend.ledger.action import CmdRunAction
    from backend.ledger.observation import Observation


IS_WINDOWS = OS_CAPS.is_windows

# Small pause after writes to let the PTY drain into the reader buffer before
# the caller grabs output. Not a correctness requirement — just a usability
# nicety so the first ``read_output`` call sees prompt echo.
_POST_WRITE_SETTLE_SECONDS = 0.1

# Bounds for waiting for a new PS1 JSON block after ``execute`` sends a line.
_PTY_PS1_WAIT_FLOOR = 60.0
_PTY_PS1_WAIT_CEIL = 3600.0

# PowerShell default prompt pattern: "PS C:\some\path>"
# Used to parse the current working directory from PTY delta output on Windows
# where PS1 JSON metadata tracking is not available.
_PS_PROMPT_RE = re.compile(r'^PS\s+(.+?)>\s*$')


def _remove_command_prefix(command_output: str, command: str) -> str:
    """Strip a leading copy of the command line from captured PTY text."""
    return command_output.lstrip().removeprefix(command.lstrip()).lstrip()


def _output_between_last_two_ps1(
    full: str, command: str
) -> tuple[str, CmdOutputMetadata]:
    """Slice stdout between the last two PS1 blocks; parse exit info from the last."""
    nfull = _norm_tty_text(full)
    matches = CmdOutputMetadata.matches_ps1_metadata(nfull)
    if len(matches) < 2:
        return full, CmdOutputMetadata(
            exit_code=-1,
            working_dir=None,
            suffix=(
                '\n[Could not isolate command output: expected PS1 JSON markers '
                'before and after the command.]\n'
            ),
        )
    prev_m, last_m = matches[-2], matches[-1]
    raw = nfull[prev_m.end() + 1 : last_m.start()]
    out = _remove_command_prefix(raw, command)
    meta = CmdOutputMetadata.from_ps1_match(last_m)
    return out.rstrip(), meta


def _argv_looks_like_bash(argv: list[str]) -> bool:
    if not argv or not argv[0]:
        return False
    base = os.path.basename(argv[0].lower())
    if base in {'bash', 'bash.exe', 'msys-bash.exe'}:
        return True
    return 'bash' in base


def _norm_tty_text(text: str) -> str:
    """Normalize CRLF so PS1 JSON regex/JSON sees stable newlines (Windows PTYs)."""
    return text.replace('\r\n', '\n').replace('\r', '\n')


# Aliases recognized by ``write_input(is_control=True)``. Keys are normalized
# to lower case and stripped. Values are control-sequence alias names fed into
# :data:`CONTROL_SEQUENCES`.
_CONTROL_ALIASES: dict[str, str] = {
    'c-c': 'c',
    'ctrl-c': 'c',
    'ctrl+c': 'c',
    '^c': 'c',
    '\x03': 'c',
    'c-d': 'd',
    'ctrl-d': 'd',
    'ctrl+d': 'd',
    '^d': 'd',
    '\x04': 'd',
    'c-z': 'z',
    'ctrl-z': 'z',
    'ctrl+z': 'z',
    '\x1a': 'z',
    'c-\\': 'backslash',
    'ctrl-\\': 'backslash',
    '\x1c': 'backslash',
    'esc': 'esc',
    'escape': 'esc',
    '\x1b': 'esc',
    'tab': 'tab',
    '\t': 'tab',
    'enter': 'enter',
    'return': 'enter',
    '\r': 'enter',
}


def _default_shell_argv() -> list[str]:
    """Pick a reasonable long-lived interactive shell for this OS."""
    if IS_WINDOWS:
        pwsh = shutil.which('pwsh')
        if pwsh:
            return [pwsh, '-NoLogo', '-NoProfile']
        powershell = shutil.which('powershell')
        if powershell:
            return [powershell, '-NoLogo', '-NoProfile']
        return ['cmd.exe']
    bash = shutil.which('bash')
    if bash:
        return [bash, '--norc', '--noprofile', '-i']
    return ['sh', '-i']


class PtyInteractiveShellSession(BaseShellSession):
    """``UnifiedShellSession`` implementation backed by a native PTY.

    Use this for *interactive* sessions — dev servers, REPLs, TUIs, wizard
    CLIs — where ``read_output`` / ``write_input`` must actually work.
    For **bash** interactives, ``execute()`` can optionally install the same
    JSON PS1 convention as :class:`BashSession` and then wait for a new
    ``###PS1JSON###`` block so ``exit_code`` and ``working_dir`` in
    :class:`CmdOutputMetadata` are accurate.  PowerShell / ``cmd`` sessions
    keep a best-effort ``execute`` (no reliable PS1) unless/until a dedicated
    prompt hook is added for those shells.

    **Env:** Set ``GRINTA_PTY_PS1=0`` to force the legacy best-effort path even
    for bash.  Pass ``enable_ps1_metadata=False`` to disable PS1 in code.
    """

    _initialized = False
    _cwd = ''

    def __init__(
        self,
        work_dir: str,
        username: str | None = None,
        no_change_timeout_seconds: int = 30,
        max_memory_mb: int | None = None,
        cancellation_service: TaskCancellationService | None = None,
        security_config: object | None = None,
        workspace_root: str | None = None,
        *,
        shell_argv: list[str] | None = None,
        dimensions: tuple[int, int] = (24, 120),
        buffer_chars: int = 1_048_576,
        enable_ps1_metadata: bool | None = None,
    ) -> None:
        self._initialized = False
        self._cwd = os.path.abspath(work_dir)
        super().__init__(
            work_dir=work_dir,
            username=username,
            no_change_timeout_seconds=no_change_timeout_seconds,
            max_memory_mb=max_memory_mb,
            cancellation_service=cancellation_service,
            security_config=security_config,
            workspace_root=workspace_root,
        )
        self._shell_argv = list(shell_argv) if shell_argv else _default_shell_argv()
        self._dimensions = dimensions
        self._buffer_chars = buffer_chars
        self._pty: InteractiveSession | None = None
        self._enable_ps1_param = enable_ps1_metadata
        self._ps1_ready = False

    def _want_ps1_metadata(self) -> bool:
        """Return True if we should use JSON PS1 tracking for this shell process."""
        if os.environ.get('GRINTA_PTY_PS1', '').strip().lower() in (
            '0',
            'false',
            'no',
        ):
            return False
        if self._enable_ps1_param is not None:
            if not self._enable_ps1_param:
                return False
            if not _argv_looks_like_bash(self._shell_argv):
                logger.warning(
                    'enable_ps1_metadata=True but the PTY command is not bash; '
                    'disabling JSON PS1 tracking.'
                )
                return False
            return True
        return _argv_looks_like_bash(self._shell_argv)

    def _ps1_wait_timeout(self) -> float:
        t = 2.0 * float(self.NO_CHANGE_TIMEOUT_SECONDS)
        return min(_PTY_PS1_WAIT_CEIL, max(_PTY_PS1_WAIT_FLOOR, t))

    def _install_bash_json_ps1(self) -> None:
        """Match ``BashSession`` PROMPT_COMMAND + PS1 so we can parse exit/cwd (bash only)."""
        pty = self._pty
        if pty is None or not self._want_ps1_metadata():
            return
        if not _argv_looks_like_bash(self._shell_argv):
            return
        try:
            ps1 = CmdOutputMetadata.to_ps1_prompt()
            # Set PS1/PS2; use shlex so embedded JSON double-quotes survive the shell
            # transport (``BashSession`` does the same via a tmux ``send_keys`` string).
            pty.write(f'export PS1={shlex.quote(ps1)}\n')
            pty.write('export PS2=""\n')
            pty.write('\n')
            time.sleep(0.2)
            if not pty.wait_for_output(
                predicate=lambda p: bool(
                    CmdOutputMetadata.matches_ps1_metadata(_norm_tty_text(p))
                ),
                timeout=25.0,
            ):
                logger.warning(
                    'JSON PS1 not detected in PTY bash output; '
                    'falling back to best-effort execute().'
                )
                self._ps1_ready = False
                return
            self._ps1_ready = True
            logger.info(
                'Pty bash session JSON PS1 ready (execute will report exit/cwd).'
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning('Failed to install JSON PS1 in PTY bash: %s', exc)
            self._ps1_ready = False

    def initialize(self) -> None:
        """Spawn the interactive shell under a PTY."""
        if self._pty is not None:
            return
        cwd = self.work_dir
        if not os.path.isdir(cwd):
            os.makedirs(cwd, exist_ok=True)
            logger.info('Created working directory: %s', cwd)

        config = InteractiveSessionConfig(
            argv=self._shell_argv,
            cwd=cwd,
            dimensions=self._dimensions,
            buffer_chars=self._buffer_chars,
        )
        session = InteractiveSession(config)
        try:
            session.start()
        except PtyUnavailableError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f'Failed to initialize PTY shell session: {exc}'
            ) from exc

        self._pty = session
        self._initialized = True
        self._install_bash_json_ps1()
        logger.info(
            'PtyInteractiveShellSession initialized (pid=%s, argv=%s, cwd=%s, '
            'ps1_ready=%s)',
            session.pid,
            self._shell_argv,
            cwd,
            self._ps1_ready,
        )

    def _execute_with_ps1_after_send(
        self, pty: InteractiveSession, command: str, ps1_count_before: int
    ) -> CmdOutputObservation:
        """Wait for a new PS1 block and build the observation (command already sent)."""
        w = self._ps1_wait_timeout()
        if not pty.wait_for_output(
            predicate=lambda p, nb=ps1_count_before: len(
                CmdOutputMetadata.matches_ps1_metadata(_norm_tty_text(p))
            )
            > nb,
            timeout=w,
        ):
            tail = pty.peek()
            meta = CmdOutputMetadata(
                exit_code=-1,
                working_dir=self.cwd,
                suffix=(
                    f'\n[Timed out after {w:.0f}s waiting for a new PS1 JSON block.]\n'
                ),
            )
            return CmdOutputObservation(
                content=tail,
                command=command,
                metadata=meta,
            )
        full = pty.peek()
        content, metadata = _output_between_last_two_ps1(full, command)
        if metadata.working_dir and str(metadata.working_dir) != self.cwd:
            self._cwd = str(metadata.working_dir)
        metadata.suffix = (
            f'\n[The command completed with exit code {metadata.exit_code}.]\n'
        )
        return CmdOutputObservation(
            content=content,
            command=command,
            metadata=metadata,
        )

    def execute(self, action: CmdRunAction) -> Observation:
        """Run one command. On bash, uses JSON PS1 markers for exit/cwd when available."""
        if self._pty is None or self._closed:
            return ErrorObservation(
                content='PTY shell session is not initialized or has been closed.'
            )
        pty = self._pty
        if not pty.is_alive():
            return ErrorObservation(content='PTY shell session is not alive.')

        command = (action.command or '').strip()
        if command and self._want_ps1_metadata() and self._ps1_ready:
            buffer = pty.peek()
            n_before = len(
                CmdOutputMetadata.matches_ps1_metadata(_norm_tty_text(buffer))
            )
            try:
                pty.send_line(command)
            except InteractiveSessionError as exc:
                return ErrorObservation(content=f'Failed to send command: {exc}')
            return self._execute_with_ps1_after_send(pty, command, n_before)

        if command:
            # Snapshot the current buffer position so we can return only the
            # delta produced by this command rather than the entire accumulated
            # PTY history.  read_output_since(very_large) returns ('', current)
            # without allocating the full buffer text.
            _, offset_before, _ = self.read_output_since(10**18)
            try:
                pty.send_line(command)
            except InteractiveSessionError as exc:
                return ErrorObservation(content=f'Failed to send command: {exc}')
            time.sleep(_POST_WRITE_SETTLE_SECONDS)
            # Return only the output produced since before the command was sent.
            content, _, _ = self.read_output_since(offset_before)
            # On Windows the shell is PowerShell/cmd — no PS1 JSON tracking.
            # Parse the embedded prompt to keep self._cwd current so every
            # observation carries the correct [Current working directory:] tag.
            if IS_WINDOWS:
                self._try_update_cwd_from_ps_prompt(content)
        else:
            content = pty.read(consume=False)

        metadata = CmdOutputMetadata(exit_code=0, working_dir=self.cwd)
        return CmdOutputObservation(
            content=content,
            command=command,
            metadata=metadata,
        )

    def read_output(self) -> str:
        """Return the current buffered PTY output without consuming it."""
        if self._pty is None:
            return ''
        return self._pty.read(consume=False)

    def _try_update_cwd_from_ps_prompt(self, content: str) -> None:
        """Parse the PowerShell prompt from PTY delta output and update self._cwd.

        The default PS prompt is ``PS <path>> ``.  We normalise CRLF first,
        then scan lines in reverse so we pick the last (most recent) prompt.
        We only accept the candidate if it resolves to an existing directory to
        guard against false positives from command output that happens to look
        like a prompt.
        """
        normalised = _norm_tty_text(content)
        for line in reversed(normalised.splitlines()):
            stripped = line.rstrip()
            # Match "PS C:\some\path>" with optional trailing spaces/ANSI
            m = _PS_PROMPT_RE.match(stripped)
            if m:
                candidate = m.group(1).strip()
                if candidate and os.path.isdir(candidate):
                    self._cwd = candidate
                return

    def read_output_since(self, offset: int) -> tuple[str, int, int]:
        """Return non-consuming output delta since ``offset``.

        Returns:
            tuple[str, int, int]:
                - delta text
                - next output cursor offset
                - total dropped chars due to ring-buffer trimming
        """
        if self._pty is None:
            return '', max(0, int(offset)), 0
        safe_offset = max(0, int(offset))
        text, next_offset = self._pty.read_since(safe_offset)
        return text, next_offset, self._pty.dropped_chars

    def write_input(self, data: str, is_control: bool = False) -> None:
        """Write raw input or a named control sequence to the PTY.

        When ``is_control=True``, ``data`` is matched case-insensitively
        against a small set of aliases (``C-c``, ``ctrl-d``, ``esc``, ``tab``,
        ...). If the alias is unknown, the raw bytes are sent verbatim so the
        caller can still push arbitrary control sequences.
        """
        if self._pty is None:
            logger.warning('write_input called on uninitialized PTY session')
            return
        if not is_control:
            if IS_WINDOWS:
                # ConPTY (Windows) uses bare CR (\r) as the Enter/submit signal.
                # A bare LF puts PowerShell into multi-line continuation mode
                # (the ``>>`` prompt).  CRLF also causes problems: the \n
                # arrives after the command has already been submitted by \r
                # and PowerShell treats it as stray input, triggering ``>>``.
                # Normalise any newline variant → \r only.
                data = data.replace('\r\n', '\n').replace('\n', '\r')
            try:
                self._pty.write(data)
            except InteractiveSessionError as exc:
                logger.warning('PTY write failed: %s', exc)
            return

        key = data.strip().lower() if len(data) > 1 else data
        alias = _CONTROL_ALIASES.get(key if isinstance(key, str) else '')
        try:
            if alias is not None and alias in CONTROL_SEQUENCES:
                self._pty.send_control(alias)
            else:
                self._pty.write(data)
        except InteractiveSessionError as exc:
            logger.warning('PTY control write failed: %s', exc)

    def resize(self, rows: int, cols: int) -> None:
        """Resize the underlying PTY window. No-op if not yet started."""
        if self._pty is None:
            return
        try:
            self._pty.resize(rows, cols)
        except InteractiveSessionError as exc:
            logger.warning('PTY resize failed: %s', exc)

    def close(self) -> None:
        """Terminate the child shell and shut down the reader thread."""
        if self._pty is not None:
            try:
                self._pty.close(grace_seconds=1.0)
            except Exception as exc:
                logger.debug('Error closing PTY session: %s', exc)
            self._pty = None
        super().close()


__all__ = [
    'PtyInteractiveShellSession',
    '_argv_looks_like_bash',
    '_default_shell_argv',
    '_output_between_last_two_ps1',
    '_remove_command_prefix',
]
