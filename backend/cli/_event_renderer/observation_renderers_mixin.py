"""Per-observation renderer methods for ``CLIEventRenderer``.

Extracted from ``backend/cli/event_renderer.py`` to keep the parent module
under the per-file LOC budget.  All methods rely on attributes/methods
defined on ``CLIEventRenderer``; this mixin is meant to be combined with
that class via multiple inheritance.
"""

from __future__ import annotations

import logging
from typing import Any

from rich import box
from rich.padding import Padding
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from backend.cli._event_renderer.apply_patch import (
    compact_apply_patch_result as _compact_apply_patch_result,
)
from backend.cli._event_renderer.apply_patch import (
    is_apply_patch_activity as _is_apply_patch_activity,
)
from backend.cli._event_renderer.apply_patch import (
    summarize_cmd_failure as _summarize_cmd_failure,
)
from backend.cli._event_renderer.constants import (
    BROWSER_TOOL_COMMANDS as _BROWSER_TOOL_COMMANDS,
)
from backend.cli._event_renderer.constants import (
    DIRECTORY_VIEW_PREFIX as _DIRECTORY_VIEW_PREFIX,
)
from backend.cli._event_renderer.delegate import (
    summarize_delegate_observation as _summarize_delegate_observation,
)
from backend.cli._event_renderer.error_panel import (
    build_error_panel as _build_error_panel,
)
from backend.cli._event_renderer.error_panel import (
    build_llm_stream_fallback_panel as _build_llm_stream_fallback_panel,
)
from backend.cli._event_renderer.error_panel import (
    use_recoverable_notice_style as _use_recoverable_notice_style,
)
from backend.cli._event_renderer.text_utils import (
    pty_output_transcript_caption as _pty_output_transcript_caption,
)
from backend.cli._event_renderer.text_utils import (
    sanitize_visible_transcript_text as _sanitize_visible_transcript_text,
)
from backend.cli._event_renderer.text_utils import (
    strip_pty_echo as _strip_pty_echo,
)
from backend.cli.layout_tokens import ACTIVITY_BLOCK_BOTTOM_PAD
from backend.cli.tool_call_display import mcp_result_user_preview
from backend.cli.transcript import (
    format_activity_delta_secondary,
    format_activity_result_secondary,
    format_activity_shell_block,
    format_callout_panel,
    strip_tool_result_validation_annotations,
)
from backend.ledger.observation import (
    AgentCondensationObservation,
    AgentStateChangedObservation,
    AgentThinkObservation,
    CmdOutputObservation,
    DelegateTaskObservation,
    ErrorObservation,
    FileDownloadObservation,
    FileEditObservation,
    FileReadObservation,
    FileWriteObservation,
    LspQueryObservation,
    MCPObservation,
    Observation,
    RecallFailureObservation,
    RecallObservation,
    ServerReadyObservation,
    StatusObservation,
    SuccessObservation,
    TaskTrackingObservation,
    TerminalObservation,
    UserRejectObservation,
)

logger = logging.getLogger(__name__)


class ObservationRenderersMixin:
    """Per-observation ``_render_*_observation`` renderers + dispatch."""

    # Dispatch table for :meth:`_handle_observation` — maps observation class
    # to the method that knows how to render it.
    _OBSERVATION_DISPATCH: tuple[tuple[type, str], ...] = (
        (AgentStateChangedObservation, '_handle_state_change'),
        (AgentThinkObservation, '_render_agent_think_observation'),
        (CmdOutputObservation, '_render_cmd_output_observation'),
        (FileEditObservation, '_render_file_edit_observation'),
        (FileWriteObservation, '_render_file_write_observation'),
        (ErrorObservation, '_render_error_observation'),
        (UserRejectObservation, '_render_user_reject_observation'),
        (RecallObservation, '_render_recall_observation'),
        (StatusObservation, '_render_status_observation'),
        (FileReadObservation, '_render_file_read_observation'),
        (MCPObservation, '_render_mcp_observation'),
        (TerminalObservation, '_render_terminal_observation'),
        (LspQueryObservation, '_render_lsp_query_observation'),
        (ServerReadyObservation, '_render_server_ready_observation'),
        (SuccessObservation, '_render_success_observation'),
        (RecallFailureObservation, '_render_recall_failure_observation'),
        (FileDownloadObservation, '_render_file_download_observation'),
        (DelegateTaskObservation, '_render_delegate_task_observation'),
        (TaskTrackingObservation, '_render_task_tracking_observation'),
        (AgentCondensationObservation, '_render_agent_condensation_observation'),
    )

    def _handle_observation(self, obs: Observation) -> None:
        """Dispatch *obs* to the appropriate ``_render_*_observation`` handler."""
        for obs_type, method_name in self._OBSERVATION_DISPATCH:
            if isinstance(obs, obs_type):
                getattr(self, method_name)(obs)
                return
        self.refresh()

    # -- Per-observation renderers (small, single-CC dispatch targets) ------

    def _render_agent_think_observation(self, obs: AgentThinkObservation) -> None:
        if bool(getattr(obs, 'suppress_cli', False)):
            self.refresh()
            return
        thought = getattr(obs, 'thought', '') or getattr(obs, 'content', '')
        self._apply_reasoning_text(thought)
        self.refresh()

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
        )
        inner = format_activity_shell_block(
            verb,
            label,
            result_message=msg,
            result_kind=result_kind,
            extra_lines=extra_lines,
            title=title if is_internal else None,
        )
        self._print_or_buffer(Padding(inner, pad=ACTIVITY_BLOCK_BOTTOM_PAD))

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
    ) -> tuple[str | None, str, list[Any] | None]:
        """Return ``(msg, result_kind, extra_lines)`` for the shell card."""
        if is_internal and _is_apply_patch_activity(title, label):
            return _compact_apply_patch_result(
                exit_code=exit_code, label=label, content=content,
            )
        # CmdOutputObservation defaults to exit_code=-1 when unknown; treat any
        # non-zero exit code (including -1) as a failure.
        if exit_code is not None and exit_code != 0:
            return self._cmd_observation_failure(exit_code, content), 'err', None
        # Plain shell success: hide verbose stdout.
        return self._cmd_observation_success(exit_code, content)

    @staticmethod
    def _cmd_observation_failure(exit_code: int, content: str) -> str:
        err_line = _summarize_cmd_failure(content)
        msg = f'exit {exit_code}'
        if err_line:
            msg += f' · {err_line}'
        return msg

    @staticmethod
    def _cmd_observation_success(
        exit_code: int | None, content: str,
    ) -> tuple[str | None, str, list[Any] | None]:
        raw_lines = (
            [ln.strip() for ln in content.split('\n') if ln.strip()]
            if content
            else []
        )
        msg: str | None = 'done' if (raw_lines or exit_code == 0) else None
        result_kind = 'ok' if exit_code == 0 else 'neutral'
        return msg, result_kind, None

    def _render_file_edit_observation(self, obs: FileEditObservation) -> None:
        self._stop_reasoning()
        from backend.cli.diff_renderer import DiffPanel

        path = getattr(obs, 'path', '')
        pending = self._take_pending_activity_card('file_edit')
        self._emit_activity_turn_header()
        self._print_or_buffer(
            Padding(
                DiffPanel(
                    obs,
                    verb=pending.verb if pending else None,
                    detail=pending.detail if pending else path,
                    secondary=pending.secondary if pending else None,
                ),
                pad=ACTIVITY_BLOCK_BOTTOM_PAD,
            )
        )

    def _render_file_write_observation(self, obs: FileWriteObservation) -> None:
        del obs
        self._stop_reasoning()
        pending = self._take_pending_activity_card('file_write')
        line_count = 0
        if pending and pending.payload:
            raw_line_count = pending.payload.get('line_count', 0)
            if isinstance(raw_line_count, int):
                line_count = raw_line_count
        delta = format_activity_delta_secondary(added=line_count)
        extra_lines: list[Any] = []
        if delta is not None:
            extra_lines.append(delta)
        if pending is not None:
            self._render_pending_activity_card(pending, extra_lines=extra_lines)

    def _render_error_observation(self, obs: ErrorObservation) -> None:
        # agent_only observations are internal system feedback (e.g. "FINISH
        # BLOCKED"). The agent still receives them in context, but they must
        # not appear in the user-facing transcript.
        if getattr(obs, 'agent_only', False):
            return
        self._stop_reasoning()
        self._flush_pending_tool_cards()
        self._clear_streaming_preview()
        error_content = getattr(obs, 'content', str(obs))
        use_notice = _use_recoverable_notice_style(error_content)
        self._append_history(
            _build_error_panel(
                error_content,
                force_notice=use_notice,
                content_width=self._console.width,
            ),
        )
        # Do not force HUD to Ready/Idle for recoverable notices — the agent
        # may still be RUNNING (e.g. before RecoveryService transitions
        # state).  Ledger HUD is driven by AgentStateChangedObservation.
        if not use_notice:
            self._hud.update_ledger('Error')

    def _render_user_reject_observation(self, obs: UserRejectObservation) -> None:
        self._flush_pending_tool_cards()
        content = getattr(obs, 'content', '')
        self._append_history(
            format_callout_panel(
                'Rejected',
                Text(content or 'Action rejected.', style='yellow'),
                accent_style='yellow',
            )
        )

    def _render_recall_observation(self, obs: RecallObservation) -> None:
        self._flush_pending_tool_cards()
        recall_type = getattr(obs, 'recall_type', None)
        label = str(recall_type.value) if recall_type else 'context'
        # Next agent step calls the LLM — show activity indicator.
        self._ensure_reasoning()
        self._reasoning.update_action(f'Recalled {label}…')
        self.refresh()

    def _render_status_observation(self, obs: StatusObservation) -> None:
        status_type = str(getattr(obs, 'status_type', '') or '')
        force_visible_status = False
        if status_type == 'delegate_progress':
            if self._handle_delegate_progress_status(obs):
                return
        elif status_type in ('retry_pending', 'retry_resuming'):
            self._handle_retry_status(obs, status_type=status_type)
            force_visible_status = True
        self._render_status_content(obs, force_visible_status=force_visible_status)

    def _handle_delegate_progress_status(self, obs: StatusObservation) -> bool:
        """Update the delegate panel; return True if the obs is fully consumed."""
        extras = getattr(obs, 'extras', None) or {}
        if self._delegate_batch_mismatch(extras.get('batch_id')):
            return True
        worker_id = str(extras.get('worker_id') or '').strip()
        if not worker_id:
            return False
        self._delegate_workers[worker_id] = self._delegate_worker_record(
            obs, extras, worker_id,
        )
        self._set_delegate_panel()
        return True

    @staticmethod
    def _delegate_worker_record(
        obs: StatusObservation, extras: Any, worker_id: str,
    ) -> dict[str, Any]:
        order = extras.get('order', 9999)
        if not isinstance(order, int):
            order = 9999
        return {
            'label': str(extras.get('worker_label') or worker_id),
            'status': str(extras.get('worker_status') or 'running'),
            'task': str(extras.get('task_description') or 'subtask'),
            'detail': str(
                extras.get('detail') or getattr(obs, 'content', '') or ''
            ),
            'order': order,
        }

    def _delegate_batch_mismatch(self, batch_id: Any) -> bool:
        return (
            batch_id is not None
            and self._delegate_batch_id is not None
            and batch_id != self._delegate_batch_id
        )

    def _handle_retry_status(
        self, obs: StatusObservation, *, status_type: str,
    ) -> None:
        extras = getattr(obs, 'extras', None) or {}
        attempt = self._coerce_positive_int(extras.get('attempt'), default=1)
        max_attempts = self._coerce_positive_int(
            extras.get('max_attempts'), default=attempt, floor=attempt,
        )
        self._hud.update_ledger('Backoff')
        prefix = 'Auto Retry' if status_type == 'retry_pending' else 'Retrying'
        self._hud.update_agent_state(f'{prefix} {attempt}/{max_attempts}')

    @staticmethod
    def _coerce_positive_int(value: Any, *, default: int, floor: int = 1) -> int:
        try:
            coerced = int(value or default)
        except (TypeError, ValueError):
            coerced = default
        return max(floor, coerced)

    def _render_status_content(
        self, obs: StatusObservation, *, force_visible_status: bool,
    ) -> None:
        content = getattr(obs, 'content', '')
        if not content:
            return
        lower_c = content.lower()
        if 'stream timed out' in lower_c or 'retrying without streaming' in lower_c:
            self._stream_fallback_count += 1
            logger.warning(
                'stream_fallback_retry: count=%d content=%r',
                self._stream_fallback_count,
                content[:120],
            )
            self._append_history(_build_llm_stream_fallback_panel())
            return
        if self._pending_activity_card is not None and not force_visible_status:
            return
        self._flush_pending_tool_cards()
        self._append_history(
            format_activity_result_secondary(
                f'status · {content}', kind='neutral',
            )
        )

    def _render_file_read_observation(self, obs: FileReadObservation) -> None:
        self._stop_reasoning()
        content = getattr(obs, 'content', '') or ''
        n_lines = len(content.splitlines()) if content else 0
        pending = self._take_pending_activity_card('file_read')
        result_message = self._file_read_result_message(content, n_lines)
        if pending is not None:
            self._render_pending_activity_card(
                pending,
                result_message=result_message,
                result_kind='neutral',
            )
        elif n_lines:
            self._append_history(
                format_activity_result_secondary(result_message, kind='neutral')
            )

    @staticmethod
    def _file_read_result_message(content: str, n_lines: int) -> str:
        """``text_editor view`` on a directory returns ``Directory contents of …:``.

        Followed by entries; report entries instead of lines for that case.
        """
        if not content.startswith(_DIRECTORY_VIEW_PREFIX):
            return f'{n_lines:,} lines' if n_lines else 'empty file'
        n_entries = max(0, n_lines - 1)
        if n_entries == 1:
            return '1 entry'
        if n_entries:
            return f'{n_entries:,} entries'
        return 'empty directory'

    def _render_mcp_observation(self, obs: MCPObservation) -> None:
        self._stop_reasoning()
        content = getattr(obs, 'content', '')
        friendly = mcp_result_user_preview(content)
        pending = self._take_pending_activity_card('mcp')
        if pending is not None:
            self._render_pending_activity_card(
                pending,
                result_message=friendly or None,
                result_kind='neutral',
            )
        elif friendly:
            self._append_history(
                format_activity_result_secondary(friendly, kind='neutral')
            )

    def _render_terminal_observation(self, obs: TerminalObservation) -> None:
        raw = getattr(obs, 'content', '') or ''
        display = strip_tool_result_validation_annotations(raw)
        content = display.strip()
        session_id = (getattr(obs, 'session_id', '') or '').strip()
        has_new = getattr(obs, 'has_new_output', None)
        # Suppress entirely when there's nothing new — these are just polling
        # reads and the "no new text" caption is noise for the human user.
        if has_new is False and not content:
            self._last_terminal_input_sent = ''
            return
        self._stop_reasoning()
        self._flush_pending_tool_cards()
        # Strip PTY character-echo lines produced when the agent injects input.
        content = self._strip_pty_echo_if_pending(content)
        if not content and not session_id and not raw.strip():
            return
        n_lines = self._terminal_visible_line_count(content)
        cap = 2000
        truncated = len(display) > cap
        if content:
            body = content[:cap] + '…' if truncated else content
            self._render_terminal_panel(
                body=body, session_id=session_id, n_lines=n_lines, truncated=truncated,
            )
            return
        self._render_terminal_caption(
            session_id=session_id,
            n_lines=n_lines,
            truncated=truncated,
            has_new=has_new,
        )

    def _strip_pty_echo_if_pending(self, content: str) -> str:
        if content and self._last_terminal_input_sent:
            content = _strip_pty_echo(content, self._last_terminal_input_sent)
            self._last_terminal_input_sent = ''
        return content

    @staticmethod
    def _terminal_visible_line_count(content: str) -> int:
        if not content:
            return 0
        return len([ln for ln in content.splitlines() if ln.strip()])

    def _render_terminal_caption(
        self,
        *,
        session_id: str,
        n_lines: int,
        truncated: bool,
        has_new: bool | None,
    ) -> None:
        caption = _pty_output_transcript_caption(
            session_id=session_id,
            n_lines=n_lines,
            truncated=truncated,
            has_output=False,
            has_new_output=has_new,
        )
        self._append_history(
            format_activity_result_secondary(caption, kind='neutral')
        )

    def _render_terminal_panel(
        self,
        *,
        body: str,
        session_id: str,
        n_lines: int,
        truncated: bool,
    ) -> None:
        title_parts: list[str] = []
        if session_id:
            title_parts.append(session_id)
        if n_lines:
            title_parts.append(f'{n_lines} line{"s" if n_lines != 1 else ""}')
        if truncated:
            title_parts.append('truncated')
        panel_title = Text(
            '  ·  '.join(title_parts) if title_parts else 'output',
            style='dim #9ca3af',
        )
        self._append_history(
            Padding(
                Panel(
                    Syntax(body, 'text', word_wrap=True, theme='ansi_dark'),
                    title=panel_title,
                    title_align='left',
                    border_style='#1e3a4a',
                    box=box.ROUNDED,
                    padding=(0, 1),
                ),
                pad=(0, 0, 1, 0),
            )
        )

    def _render_lsp_query_observation(self, obs: LspQueryObservation) -> None:
        self._stop_reasoning()
        available = getattr(obs, 'available', True)
        content = getattr(obs, 'content', '') or ''
        pending = self._take_pending_activity_card('lsp')
        result_message = self._lsp_result_message(available=available, content=content)
        if pending is not None:
            self._render_pending_activity_card(
                pending,
                result_message=result_message,
                result_kind='neutral',
            )
        elif result_message:
            self._append_history(
                format_activity_result_secondary(result_message, kind='neutral')
            )

    @staticmethod
    def _lsp_result_message(*, available: bool, content: str) -> str | None:
        if not available:
            return 'code navigation unavailable'
        if not content.strip():
            return None
        lines = [line for line in content.split('\n') if line.strip()]
        if not lines:
            return None
        preview = lines[0][:80]
        suffix = f' · {len(lines)} lines' if len(lines) > 1 else ''
        return f'{preview}{suffix}'

    def _render_server_ready_observation(self, obs: ServerReadyObservation) -> None:
        self._flush_pending_tool_cards()
        url = getattr(obs, 'url', '')
        port = getattr(obs, 'port', '')
        label = url or f'port {port}'
        self._append_history(
            format_activity_result_secondary(
                f'server ready · {label}', kind='ok',
            ),
        )

    def _render_success_observation(self, obs: SuccessObservation) -> None:
        self._flush_pending_tool_cards()
        content = getattr(obs, 'content', '')
        if content:
            self._append_history(
                format_activity_result_secondary(content, kind='ok'),
            )

    def _render_recall_failure_observation(
        self, obs: RecallFailureObservation,
    ) -> None:
        self._flush_pending_tool_cards()
        error_msg = getattr(obs, 'error_message', '')
        recall_type = getattr(obs, 'recall_type', None)
        label = str(recall_type.value) if recall_type else 'recall'
        if error_msg:
            self._append_history(
                format_activity_result_secondary(
                    f'{label} failed · {error_msg}', kind='err',
                )
            )

    def _render_file_download_observation(
        self, obs: FileDownloadObservation,
    ) -> None:
        self._flush_pending_tool_cards()
        path = getattr(obs, 'file_path', '')
        self._append_history(
            format_activity_result_secondary(
                f'downloaded · {path}', kind='neutral',
            ),
        )

    def _render_delegate_task_observation(
        self, obs: DelegateTaskObservation,
    ) -> None:
        self._stop_reasoning()
        pending = self._take_pending_activity_card('delegate')
        result_message, result_kind, extra_lines = _summarize_delegate_observation(obs)
        if pending is not None:
            self._render_pending_activity_card(
                pending,
                result_message=result_message,
                result_kind=result_kind,
                extra_lines=extra_lines,
            )
            return
        if result_message is not None:
            self._append_history(
                format_activity_result_secondary(result_message, kind=result_kind),
            )
        for line in extra_lines:
            self._append_history(line)

    def _render_task_tracking_observation(
        self, obs: TaskTrackingObservation,
    ) -> None:
        task_list = getattr(obs, 'task_list', None)
        cmd = getattr(obs, 'command', '')
        if task_list is not None and cmd == 'update':
            self._set_task_panel(task_list)
        content = _sanitize_visible_transcript_text(
            strip_tool_result_validation_annotations(
                (getattr(obs, 'content', None) or '').strip()
            )
        )
        body = '' if (task_list is not None and cmd == 'update') else content
        if body:
            for line in body.splitlines():
                self._append_history(
                    format_activity_result_secondary(line, kind='neutral')
                )
        self.refresh()

    def _render_agent_condensation_observation(
        self, obs: AgentCondensationObservation,
    ) -> None:
        del obs


__all__ = ['ObservationRenderersMixin']
