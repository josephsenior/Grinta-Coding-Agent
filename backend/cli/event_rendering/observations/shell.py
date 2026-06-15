"""Observation renderers — shell domain."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.cli._typing import ObservationRenderersHost

    _ObservationRenderersBase = ObservationRenderersHost
else:
    _ObservationRenderersBase = object

from rich.padding import Padding

from backend.cli._typing import ObservationRenderersHost
from backend.cli.display.transcript import (
    format_activity_shell_block,
    strip_tool_result_validation_annotations,
)
from backend.cli.event_rendering.constants import (
    BROWSER_TOOL_COMMANDS as _BROWSER_TOOL_COMMANDS,
)
from backend.cli.event_rendering.observations.shell_helpers import (
    _cmd_stdout_syntax_extras,
    _looks_like_command_echo,
)
from backend.cli.event_rendering.text_utils import (
    summarize_cmd_failure as _summarize_cmd_failure,
)
from backend.cli.layout_tokens import ACTIVITY_BLOCK_BOTTOM_PAD
from backend.ledger.observation import (
    CmdOutputObservation,
)

logger = logging.getLogger(__name__)


class _ObsShellMixin(_ObservationRenderersBase):
    def _render_cmd_output_observation(self, obs: CmdOutputObservation) -> None:
        self._stop_reasoning()
        self._flush_pending_activity_card()
        if getattr(obs, 'hidden', False):
            self._pending_shell_action = None
            self._pending_shell_command = None
            return
        # Browser tool completions reuse CmdOutputObservation. The Browser
        # card was already printed when the action was dispatched; skip the
        # ghost ``Terminal / Ran / $ (command) / done`` row.
        obs_cmd = (getattr(obs, 'command', '') or '').strip().lower()
        if obs_cmd in _BROWSER_TOOL_COMMANDS:
            self._reset_pending_shell()
            return
        exit_code = self._cmd_observation_exit_code(obs)
        raw = (getattr(obs, 'content', '') or '').strip()
        content = strip_tool_result_validation_annotations(raw)
        verb, label, title, is_internal = self._consume_pending_shell()
        msg, result_kind, extra_lines = self._cmd_observation_summary(
            label=label,
            title=title,
            is_internal=is_internal,
            exit_code=exit_code,
            content=content,
            command=self._pending_shell_command or '',
        )
        inner = format_activity_shell_block(
            verb,
            label,
            result_message=msg,
            result_kind=result_kind,
            extra_lines=extra_lines,
            title=title if is_internal else None,
            badge_label='execute_bash' if not is_internal else None,
        )
        self._print_or_buffer(Padding(inner, pad=ACTIVITY_BLOCK_BOTTOM_PAD))
        self._pending_shell_command = None

    def _reset_pending_shell(self) -> None:
        self._pending_shell_action = None
        self._pending_shell_command = None
        self._pending_shell_title = None
        self._pending_shell_is_internal = False

    def _consume_pending_shell(self) -> tuple[str, str, str | None, bool]:
        pending = self._pending_shell_action
        title = self._pending_shell_title
        is_internal = self._pending_shell_is_internal
        self._reset_pending_shell()
        verb = pending[0] if pending else 'Ran'
        label = pending[1] if pending else '$ (command)'
        return verb, label, title, is_internal

    @staticmethod
    def _cmd_observation_exit_code(obs: CmdOutputObservation) -> int | None:
        exit_code = getattr(obs, 'exit_code', None)
        if exit_code is None:
            meta = getattr(obs, 'metadata', None)
            exit_code = getattr(meta, 'exit_code', None) if meta else None
        return exit_code

    def _cmd_observation_summary(
        self,
        *,
        label: str,
        title: str | None,
        is_internal: bool,
        exit_code: int | None,
        content: str,
        command: str = '',
    ) -> tuple[str | None, str, list[Any] | None]:
        """Return ``(msg, result_kind, extra_lines)`` for the shell card."""
        # CmdOutputObservation defaults to exit_code=-1 when unknown; treat any
        # non-zero exit code (including -1) as a failure.
        if exit_code is not None and exit_code != 0:
            msg = self._cmd_observation_failure(exit_code, content)
            extras = self._cmd_observation_failure_extras(content)
            return msg, 'err', extras
        # Plain shell success: hide verbose stdout.
        return self._cmd_observation_success(exit_code, content, command=command)

    @staticmethod
    def _cmd_observation_failure(exit_code: int, content: str) -> str:
        err_line = _summarize_cmd_failure(content)
        msg = f'exit {exit_code}'
        if err_line:
            msg += f' · {err_line}'
        return msg

    @staticmethod
    def _cmd_observation_failure_extras(content: str) -> list[Any] | None:
        """Return extra lines for a failed command's error output."""
        from backend.cli.display.transcript import format_shell_output_block

        raw_lines = [ln.rstrip() for ln in content.split('\n')] if content else []
        if not raw_lines:
            return None
        preview_lines = [ln for ln in raw_lines if not _looks_like_command_echo(ln)][:5]
        if not preview_lines:
            return None
        return [format_shell_output_block(preview_lines, kind='err')]

    @staticmethod
    def _cmd_observation_success(
        exit_code: int | None,
        content: str,
        command: str = '',
    ) -> tuple[str | None, str, list[Any] | None]:
        [ln.rstrip() for ln in content.split('\n')] if content else []
        result_kind = 'ok' if exit_code == 0 else 'neutral'

        syntax_extras = _cmd_stdout_syntax_extras(content)
        if syntax_extras is not None:
            msg: str | None = None
            return msg, result_kind, syntax_extras

        # Successful commands: suppress stdout to keep transcript scan-able.
        # Only show exit code.
        if exit_code is not None:
            return f'exit {exit_code}', result_kind, None
        return None, result_kind, None
