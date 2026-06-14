"""Per-observation renderer methods for ``CLIEventRenderer``.

Extracted from ``backend/cli/event_renderer.py`` to keep the parent module
under the per-file LOC budget.  All methods rely on attributes/methods
defined on ``CLIEventRenderer``; this mixin is meant to be combined with
that class via multiple inheritance.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from backend.cli._typing import ObservationRenderersHost

    _ObservationRenderersBase = ObservationRenderersHost
else:
    _ObservationRenderersBase = object

from rich import box
from rich.padding import Padding
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from backend.cli._event_renderer.constants import (
    BROWSER_TOOL_COMMANDS as _BROWSER_TOOL_COMMANDS,
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
    sanitize_visible_transcript_text as _sanitize_visible_transcript_text,
)
from backend.cli._event_renderer.text_utils import (
    strip_pty_echo as _strip_pty_echo,
)
from backend.cli._event_renderer.text_utils import (
    summarize_cmd_failure as _summarize_cmd_failure,
)
from backend.cli._tool_display.preview import (
    file_read_syntax_highlight as _file_read_syntax_highlight,
)
from backend.cli._typing import ObservationRenderersHost
from backend.cli.layout_tokens import ACTIVITY_BLOCK_BOTTOM_PAD
from backend.cli.theme import (
    CLR_OUTPUT_PANEL_BORDER,
    CLR_OUTPUT_PANEL_TITLE,
    CLR_QUESTION_TEXT,
    CLR_STATUS_WARN,
    NAVY_BG,
    get_grinta_pygments_style,
)
from backend.cli.tool_call_display import (
    mcp_result_syntax_extras,
    mcp_result_user_preview,
)
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
    AnalyzeProjectStructureObservation,
    BrowserScreenshotObservation,
    CmdOutputObservation,
    DelegateTaskObservation,
    ErrorObservation,
    FileDownloadObservation,
    FileEditObservation,
    FileReadObservation,
    FileWriteObservation,
    FindSymbolsObservation,
    GlobObservation,
    GrepObservation,
    LspQueryObservation,
    MCPObservation,
    Observation,
    ReadSymbolsObservation,
    RecallFailureObservation,
    RecallObservation,
    ServerReadyObservation,
    StatusObservation,
    SuccessObservation,
    TaskTrackingObservation,
    TerminalObservation,
    UserRejectObservation,
)
from backend.ledger.observation.error import (
    ERROR_CATEGORY_NETWORK,
    ERROR_CATEGORY_RATE_LIMIT,
    ERROR_CATEGORY_TIMEOUT,
)

logger = logging.getLogger(__name__)

# Error categories that are transient and already reflected in the HUD bar.
# Rendering these in the history pollutes the transcript with redundant info.
_SUPPRESS_FROM_HISTORY_CATEGORIES: frozenset[str] = frozenset(
    {
        ERROR_CATEGORY_TIMEOUT,
        ERROR_CATEGORY_NETWORK,
        ERROR_CATEGORY_RATE_LIMIT,
    }
)


def _terminal_output_lexer(body: str) -> str:
    """Pick a Pygments lexer for PTY/shell output (JSON, tracebacks, plain)."""
    raw = body or ''
    head = raw.lstrip()
    if not head:
        return 'text'
    if head[0] in '{[':
        try:
            json.loads(raw[: min(len(raw), 500_000)])
            return 'json'
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    low = raw.lower()
    if 'traceback (most recent call last)' in low:
        return 'pytb'
    return 'text'


def _cmd_stdout_syntax_extras(content: str) -> list[Any] | None:
    """Rich Syntax block for bulky structured shell stdout (JSON, tracebacks, …).

    Plain prose/log lines stay hidden on success — only non-``text`` lexers
    (JSON, Python tracebacks, …) get an inline preview.
    """
    c = (content or '').strip()
    if len(c) < 120:
        return None
    n_lines = len([ln for ln in c.splitlines() if ln.strip()])
    lex = _terminal_output_lexer(c)
    if lex == 'text':
        return None
    cap = 12_000
    body = c[:cap] + ('…' if len(c) > cap else '')
    return [
        Syntax(
            body,
            lex,
            word_wrap=True,
            theme=get_grinta_pygments_style(),
            line_numbers=n_lines > 10,
            background_color=NAVY_BG,
        )
    ]


def _looks_like_command_echo(line: str) -> bool:
    """Check if a line is likely the echoed command (not actual output)."""
    stripped_line = line.strip()
    if not stripped_line:
        return True
    if (
        stripped_line.startswith('$ ')
        or stripped_line.startswith('❯ ')
        or stripped_line.startswith('> ')
    ):
        return True
    return False


class ObservationRenderersMixin(_ObservationRenderersBase):
    """Per-observation ``_render_*_observation`` renderers + dispatch."""

    _pending_shell_command: str | None
    _pending_shell_action: tuple[str, str] | None
    _pending_shell_title: str | None
    _pending_shell_is_internal: bool

    # Dispatch table for :meth:`_handle_observation` — maps observation class
    # to the method that knows how to render it.
    _OBSERVATION_DISPATCH: tuple[tuple[type, str], ...] = (
        (AgentStateChangedObservation, '_handle_state_change'),
        (AgentThinkObservation, '_render_agent_think_observation'),
        (BrowserScreenshotObservation, '_render_browser_screenshot_observation'),
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
        (GrepObservation, '_render_grep_observation'),
        (GlobObservation, '_render_glob_observation'),
        (FindSymbolsObservation, '_render_find_symbols_observation'),
        (ReadSymbolsObservation, '_render_read_symbols_observation'),
        (
            AnalyzeProjectStructureObservation,
            '_render_analyze_project_structure_observation',
        ),
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

    def _render_browser_screenshot_observation(
        self, obs: BrowserScreenshotObservation
    ) -> None:
        """Same UX as browser ``CmdOutputObservation``: suppress duplicate shell row."""
        del obs
        self._stop_reasoning()
        self._flush_pending_activity_card()
        self._reset_pending_shell()
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
        from backend.cli.transcript import format_shell_output_block

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

    def _render_file_edit_observation(self, obs: FileEditObservation) -> None:
        self._stop_reasoning()
        from backend.cli.diff_renderer import DiffPanel
        from backend.cli.transcript import strip_indentation_warnings

        # Strip agent-facing indentation warnings from user-visible content
        if hasattr(obs, 'content') and obs.content:
            obs.content = strip_indentation_warnings(obs.content)

        path = getattr(obs, 'path', '')
        pending = cast(Any, self._take_pending_activity_card('file_edit'))
        self._emit_activity_turn_header()
        self._print_or_buffer(
            Padding(
                DiffPanel(
                    obs,
                    verb=pending.verb if pending else None,
                    detail=pending.detail if pending else path,
                    secondary=pending.secondary if pending else None,
                    title=pending.title if pending else None,
                    badge_label=pending.badge_label if pending else 'file_edit',
                ),
                pad=ACTIVITY_BLOCK_BOTTOM_PAD,
            )
        )

    def _render_file_write_observation(self, obs: FileWriteObservation) -> None:
        del obs
        self._stop_reasoning()
        pending = cast(Any, self._take_pending_activity_card('file_write'))
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
        if getattr(obs, 'agent_only', False):
            return
        # Skip transient provider/network/timeout notices from history — the
        # HUD bar already reflects the agent state (Backoff/Rate Limited/etc.)
        # and these panels pollute the transcript with redundant information.
        error_category = getattr(obs, 'error_category', None)
        if error_category in _SUPPRESS_FROM_HISTORY_CATEGORIES:
            return
        # notify_ui_only errors are user-facing toasts only — they should not
        # appear in the transcript history either.
        if getattr(obs, 'notify_ui_only', False):
            return
        self._stop_reasoning()
        self._flush_pending_tool_cards()
        self._clear_streaming_preview()
        error_content = getattr(obs, 'content', str(obs))
        # Use the structured category set by RecoveryService at the exception
        # site — no text matching needed for typed provider/runtime errors.
        use_notice = _use_recoverable_notice_style(
            error_content, error_category=error_category
        )
        if use_notice:
            last_notice_content = getattr(self, '_last_notice_error_content', None)
            if (
                isinstance(last_notice_content, str)
                and last_notice_content == error_content
            ):
                return
            setattr(self, '_last_notice_error_content', error_content)
        else:
            setattr(self, '_last_notice_error_content', None)
        self._append_history(
            _build_error_panel(
                error_content,
                force_notice=use_notice,
                error_category=error_category,
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
                Text(content or 'Action rejected.', style=CLR_QUESTION_TEXT),
                accent_style=CLR_STATUS_WARN,
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
        self._maybe_update_mcp_status(status_type, obs)
        if self._try_early_return_for_status(obs, status_type):
            return
        self._render_status_content(
            obs,
            force_visible_status=False,
            retry_signature=None,
        )

    def _maybe_update_mcp_status(
        self, status_type: str, obs: StatusObservation
    ) -> None:
        if status_type not in ('mcp_ready', 'mcp_connected'):
            return
        extras = getattr(obs, 'extras', None) or {}
        mcp_n = int(extras.get('connected_client_count') or 0)
        self._hud.update_mcp_servers(mcp_n)

    def _try_early_return_for_status(
        self, obs: StatusObservation, status_type: str
    ) -> bool:
        if status_type == 'delegate_progress':
            return self._handle_delegate_progress_status(obs)
        if status_type in (
            'retry_pending',
            'retry_resuming',
            'llm_retry_pending',
            'llm_retry_resuming',
        ):
            return self._handle_retry_status_with_dedup(obs, status_type)
        setattr(self, '_last_retry_status_signature', None)
        return False

    def _handle_retry_status_with_dedup(
        self, obs: StatusObservation, status_type: str
    ) -> bool:
        self._handle_retry_status(obs, status_type=status_type)
        extras = getattr(obs, 'extras', None) or {}
        retry_sig = (
            status_type,
            str(extras.get('attempt') or ''),
            str(extras.get('max_attempts') or ''),
            str(extras.get('reason') or ''),
            str(extras.get('delay_seconds') or ''),
        )
        if getattr(self, '_last_retry_status_signature', None) == retry_sig:
            return True
        setattr(self, '_last_retry_status_signature', retry_sig)
        return True

    def _handle_delegate_progress_status(self, obs: StatusObservation) -> bool:
        """Update the delegate panel; return True if the obs is fully consumed."""
        extras = getattr(obs, 'extras', None) or {}
        if self._delegate_batch_mismatch(extras.get('batch_id')):
            return True
        worker_id = str(extras.get('worker_id') or '').strip()
        if not worker_id:
            return False
        previous = self._delegate_workers.get(worker_id, {})
        self._delegate_workers[worker_id] = self._delegate_worker_record(
            obs,
            extras,
            worker_id,
            previous=previous,
        )
        self._set_delegate_panel()
        return True

    @staticmethod
    def _extract_order(extras: Any) -> int:
        order = extras.get('order', 9999)
        return order if isinstance(order, int) else 9999

    @staticmethod
    def _extract_detail(obs: StatusObservation, extras: Any) -> str:
        return str(extras.get('detail') or getattr(obs, 'content', '') or '')

    @staticmethod
    def _compute_worker_timing(
        status: str,
        previous: dict[str, Any] | None,
        now: float,
    ) -> tuple[float, float | None]:
        prev = previous or {}
        started_at = prev.get('started_at', now)
        finished_at = prev.get('finished_at')
        if status in ('done', 'failed') and finished_at is None:
            finished_at = now
        return started_at, finished_at

    @staticmethod
    def _compute_worker_action_tracking(
        status: str,
        detail: str,
        previous: dict[str, Any] | None,
    ) -> tuple[str, int]:
        prev = previous or {}
        last_action = prev.get('last_action', '')
        if status == 'running' and detail:
            last_action = detail
        action_count = prev.get('action_count', 0)
        if status == 'running' and detail and detail != prev.get('last_action', ''):
            action_count += 1
        return last_action, action_count

    @staticmethod
    def _delegate_worker_record(
        obs: StatusObservation,
        extras: Any,
        worker_id: str,
        previous: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        order = ObservationRenderersMixin._extract_order(extras)
        status = str(extras.get('worker_status') or 'running')
        now = time.monotonic()
        started_at, finished_at = ObservationRenderersMixin._compute_worker_timing(
            status,
            previous,
            now,
        )
        detail = ObservationRenderersMixin._extract_detail(obs, extras)
        last_action, action_count = (
            ObservationRenderersMixin._compute_worker_action_tracking(
                status,
                detail,
                previous,
            )
        )
        return {
            'label': str(extras.get('worker_label') or worker_id),
            'status': status,
            'task': str(extras.get('task_description') or 'subtask'),
            'detail': detail,
            'order': order,
            'started_at': started_at,
            'finished_at': finished_at,
            'last_action': last_action,
            'action_count': action_count,
        }

    def _delegate_batch_mismatch(self, batch_id: Any) -> bool:
        return (
            batch_id is not None
            and self._delegate_batch_id is not None
            and batch_id != self._delegate_batch_id
        )

    def _handle_retry_status(
        self,
        obs: StatusObservation,
        *,
        status_type: str,
    ) -> None:
        extras = getattr(obs, 'extras', None) or {}
        attempt = self._coerce_positive_int(extras.get('attempt'), default=1)
        max_attempts = self._coerce_positive_int(
            extras.get('max_attempts'),
            default=attempt,
            floor=attempt,
        )
        self._hud.update_ledger('Backoff')
        if status_type in ('retry_pending', 'llm_retry_pending'):
            delay_seconds = extras.get('delay_seconds')
            try:
                delay = float(delay_seconds) if delay_seconds else 10.0
            except (TypeError, ValueError):
                delay = 10.0
            delay_str = f'{int(delay)}s' if delay >= 1 else '<1s'
            self._hud.update_agent_state(
                f'Backoff {attempt}/{max_attempts} (retrying in {delay_str})'
            )
        else:
            self._hud.update_agent_state(f'Retrying {attempt}/{max_attempts}')

    @staticmethod
    def _coerce_positive_int(value: Any, *, default: int, floor: int = 1) -> int:
        try:
            coerced = int(value or default)
        except (TypeError, ValueError):
            coerced = default
        return max(floor, coerced)

    def _render_status_content(
        self,
        obs: StatusObservation,
        *,
        force_visible_status: bool,
        retry_signature: tuple[str, str] | None = None,
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
        if retry_signature is not None:
            last_retry_signature = getattr(self, '_last_retry_status_signature', None)
            if last_retry_signature == retry_signature:
                return
            setattr(self, '_last_retry_status_signature', retry_signature)
        self._flush_pending_tool_cards()
        self._append_history(
            format_activity_result_secondary(
                f'status · {content}',
                kind='neutral',
            )
        )

    def _render_file_read_observation(self, obs: FileReadObservation) -> None:
        self._stop_reasoning()
        content = getattr(obs, 'content', '') or ''
        file_path = getattr(obs, 'path', None)
        n_lines = len(content.splitlines()) if content else 0
        start_line = getattr(obs, 'start', None) or 1
        end_line = getattr(obs, 'end', None)
        if start_line == 1 and (end_line is None or end_line == -1):
            result = f'lines 1–{n_lines}' if n_lines else ''
        elif end_line and end_line != -1:
            result = f'lines {start_line}–{end_line}'
        else:
            result = f'lines {start_line}–{n_lines}' if n_lines else ''

        # Try to add syntax highlighting
        extra_lines = None
        if n_lines > 0:
            extra_lines = _file_read_syntax_highlight(content, file_path)

        if result:
            self._emit_activity_turn_header()
            self._print_or_buffer(
                Padding(
                    format_activity_result_secondary(result, kind='neutral'),
                    pad=ACTIVITY_BLOCK_BOTTOM_PAD,
                )
            )
        if extra_lines:
            for line in extra_lines:
                self._append_history(line)

    @staticmethod
    def _file_read_result_message(content: str, n_lines: int) -> str:
        return ''

    def _render_mcp_observation(self, obs: MCPObservation) -> None:
        self._stop_reasoning()
        content = getattr(obs, 'content', '')
        name = getattr(obs, 'name', '')
        # Orient MCP tools — emit result metric as dim line
        _orient_mcp_names = {'web_search_exa', 'web_fetch_exa', 'resolve-library-id', 'query-docs'}
        if name in _orient_mcp_names:
            result = self._orient_mcp_result(name, content)
            if result:
                self._emit_activity_turn_header()
                self._print_or_buffer(
                    Padding(
                        format_activity_result_secondary(result, kind='neutral'),
                        pad=ACTIVITY_BLOCK_BOTTOM_PAD,
                    )
                )
            return
        friendly = mcp_result_user_preview(content)
        extras = mcp_result_syntax_extras(content)
        pending = cast(Any, self._take_pending_activity_card('mcp'))
        if pending is not None:
            self._render_pending_activity_card(
                pending,
                result_message=friendly or None,
                result_kind='neutral',
                extra_lines=extras,
            )
        elif friendly:
            self._append_history(
                format_activity_result_secondary(friendly, kind='neutral')
            )

    @staticmethod
    def _orient_mcp_result(name: str, content: str) -> str | None:
        """Extract result metric from orient MCP tool responses."""
        s = (content or '').strip()
        if not s:
            return None
        try:
            data = json.loads(s)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
        if isinstance(data, dict):
            # Check for error payload
            error = data.get('error') or data.get('isError')
            if error:
                return 'failed'
            # Try to extract count from various payload shapes
            for key in ('total_count', 'count', 'matches', 'total'):
                v = data.get(key)
                if isinstance(v, int):
                    if v == 0:
                        return 'no results' if name in ('web_search',) else 'no results'
                    return f'{v} results'
            # Check items/results array
            for key in ('items', 'results', 'entries', 'documents', 'content'):
                items = data.get(key)
                if isinstance(items, list):
                    count = len(items)
                    if count == 0:
                        return 'no results'
                    return f'{count} results'
        if isinstance(data, list):
            count = len(data)
            if count == 0:
                return 'no results'
            return f'{count} results'
        return None

    def _render_terminal_observation(self, obs: TerminalObservation) -> None:
        raw = getattr(obs, 'content', '') or ''
        display = strip_tool_result_validation_annotations(raw)
        content = display.strip()
        # Strip ANSI escape sequences from PTY/interactive terminal output
        if content:
            content = Text.from_ansi(content).plain
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
        if not content and not raw.strip():
            return
        if content:
            self._render_terminal_panel(body=content)
            return

    def _strip_pty_echo_if_pending(self, content: str) -> str:
        if content and self._last_terminal_input_sent:
            content = _strip_pty_echo(content, self._last_terminal_input_sent)
            self._last_terminal_input_sent = ''
        return content

    TERMINAL_LINE_LIMIT = 12

    def _render_terminal_panel(self, *, body: str) -> None:
        lines = body.splitlines()
        if len(lines) > self.TERMINAL_LINE_LIMIT:
            body = '\n'.join(lines[: self.TERMINAL_LINE_LIMIT])
        panel_title = Text('$ ', style=CLR_OUTPUT_PANEL_TITLE)
        self._append_history(
            Padding(
                Panel(
                    Syntax(
                        body,
                        _terminal_output_lexer(body),
                        word_wrap=True,
                        theme=get_grinta_pygments_style(),
                        background_color=NAVY_BG,
                    ),
                    title=panel_title,
                    title_align='left',
                    border_style=CLR_OUTPUT_PANEL_BORDER,
                    box=box.ROUNDED,
                    padding=(0, 1),
                ),
                pad=ACTIVITY_BLOCK_BOTTOM_PAD,
            )
        )

    def _render_lsp_query_observation(self, obs: LspQueryObservation) -> None:
        self._stop_reasoning()
        available = getattr(obs, 'available', True)
        content = getattr(obs, 'content', '') or ''
        result = self._orient_lsp_result(available=available, content=content)
        if result:
            self._emit_activity_turn_header()
            self._print_or_buffer(
                Padding(
                    format_activity_result_secondary(result, kind='neutral'),
                    pad=ACTIVITY_BLOCK_BOTTOM_PAD,
                )
            )

    @staticmethod
    def _orient_lsp_result(*, available: bool, content: str) -> str | None:
        if not available:
            return 'unavailable'
        if not content.strip():
            return None
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError, ValueError):
            data = None
        if isinstance(data, dict):
            # definitions/references → N results
            for key in ('definitions', 'references'):
                items = data.get(key)
                if isinstance(items, list):
                    count = len(items)
                    if count == 0:
                        return None
                    noun = key.rstrip('s')
                    return f'{count} {noun}{"s" if count != 1 else ""}'
            # hover → completed
            if 'hover' in data or 'contents' in data:
                return 'completed'
            # list_symbols → N symbols
            symbols = data.get('symbols') or data.get('symbol_list')
            if isinstance(symbols, list):
                return f'{len(symbols)} symbols'
            # diagnostics → N issues / clean
            diagnostics = data.get('diagnostics') or data.get('issues')
            if isinstance(diagnostics, list):
                count = len(diagnostics)
                if count == 0:
                    return 'clean'
                return f'{count} issue{"s" if count != 1 else ""}'
            # code_action → N actions
            actions = data.get('actions')
            if isinstance(actions, list):
                return f'{len(actions)} actions'
        if isinstance(data, list):
            return f'{len(data)} results'
        lines = [line for line in content.split('\n') if line.strip()]
        if not lines:
            return None
        return f'{len(lines)} results'

    def _render_grep_observation(self, obs: GrepObservation) -> None:
        self._stop_reasoning()
        content = obs.error or obs.content or ''
        result = self._orient_grep_result(
            query=obs.pattern,
            content=content,
            match_count=obs.match_count,
            file_count=obs.file_count,
            output_mode=getattr(obs, 'output_mode', 'files_with_matches'),
            error=obs.error,
        )
        if result:
            self._emit_activity_turn_header()
            self._print_or_buffer(
                Padding(
                    format_activity_result_secondary(result, kind='neutral'),
                    pad=ACTIVITY_BLOCK_BOTTOM_PAD,
                )
            )

    @staticmethod
    def _orient_grep_result(
        *,
        query: str,
        content: str,
        match_count: int,
        file_count: int,
        output_mode: str,
        error: str | None,
    ) -> str | None:
        if error:
            return f'failed · {error[:60]}'
        if output_mode == 'files_with_matches':
            if file_count == 0:
                return 'no matches'
            return f'{file_count} file{"s" if file_count != 1 else ""}'
        if output_mode == 'count':
            if match_count == 0:
                return 'no matches'
            return f'{match_count} match{"es" if match_count != 1 else ""}'
        if output_mode == 'content':
            if match_count == 0 and file_count == 0:
                return 'no matches'
            if file_count:
                return f'{match_count} match{"es" if match_count != 1 else ""} · {file_count} file{"s" if file_count != 1 else ""}'
            return f'{match_count} match{"es" if match_count != 1 else ""}'
        # Default
        if match_count == 0 and file_count == 0:
            return 'no matches'
        if file_count:
            return f'{file_count} file{"s" if file_count != 1 else ""}'
        return f'{match_count} match{"es" if match_count != 1 else ""}'

    def _render_glob_observation(self, obs: GlobObservation) -> None:
        self._stop_reasoning()
        content = obs.error or obs.content or ''
        result = self._orient_glob_result(
            content=content,
            file_count=obs.file_count,
            error=obs.error,
        )
        if result:
            self._emit_activity_turn_header()
            self._print_or_buffer(
                Padding(
                    format_activity_result_secondary(result, kind='neutral'),
                    pad=ACTIVITY_BLOCK_BOTTOM_PAD,
                )
            )

    @staticmethod
    def _orient_glob_result(
        *,
        content: str,
        file_count: int,
        error: str | None,
    ) -> str | None:
        if error:
            return f'failed · {error[:60]}'
        if file_count == 0:
            return 'no files'
        return f'{file_count} file{"s" if file_count != 1 else ""}'

    def _render_find_symbols_observation(self, obs: FindSymbolsObservation) -> None:
        self._stop_reasoning()
        result = self._orient_find_symbols_result(
            candidates=obs.candidates,
            error=obs.error,
        )
        if result:
            self._emit_activity_turn_header()
            self._print_or_buffer(
                Padding(
                    format_activity_result_secondary(result, kind='neutral'),
                    pad=ACTIVITY_BLOCK_BOTTOM_PAD,
                )
            )

    @staticmethod
    def _orient_find_symbols_result(
        *,
        candidates: list[Any],
        error: str | None,
    ) -> str | None:
        if error:
            return f'failed · {error[:60]}'
        symbol_count = len(candidates)
        file_count = len({
            str(item.get('path') or '')
            for item in candidates
            if item.get('path')
        })
        if symbol_count == 0:
            return 'no symbols'
        if file_count <= 1:
            return f'{symbol_count} symbol{"s" if symbol_count != 1 else ""}'
        return f'{symbol_count} symbol{"s" if symbol_count != 1 else ""} · {file_count} file{"s" if file_count != 1 else ""}'

    def _render_read_symbols_observation(self, obs: ReadSymbolsObservation) -> None:
        self._stop_reasoning()
        result = self._orient_read_symbols_result(
            available=not bool(obs.error),
            content=obs.error or obs.content or '',
        )
        if result:
            self._emit_activity_turn_header()
            self._print_or_buffer(
                Padding(
                    format_activity_result_secondary(result, kind='neutral'),
                    pad=ACTIVITY_BLOCK_BOTTOM_PAD,
                )
            )

    def _render_analyze_project_structure_observation(
        self, obs: AnalyzeProjectStructureObservation
    ) -> None:
        self._stop_reasoning()
        result = self._orient_analyze_result(
            available=not bool(obs.error),
            content=obs.error or obs.content or '',
        )
        if result:
            self._emit_activity_turn_header()
            self._print_or_buffer(
                Padding(
                    format_activity_result_secondary(result, kind='neutral'),
                    pad=ACTIVITY_BLOCK_BOTTOM_PAD,
                )
            )

    @staticmethod
    def _orient_read_symbols_result(*, available: bool, content: str) -> str | None:
        if not available:
            return 'unavailable'
        if not content.strip():
            return None
        # Parse summary from content
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        if not lines:
            return None
        # Try to count resolved vs ambiguous vs not_found
        resolved = sum(1 for line in lines if line.startswith('resolved') or '->' in line)
        ambiguous = sum(1 for line in lines if line.startswith('ambiguous') or '~>' in line)
        not_found = sum(1 for line in lines if line.startswith('not found') or line.startswith('not_found'))
        total = resolved + ambiguous + not_found
        if total == 0:
            return None
        parts = []
        if resolved:
            parts.append(f'{resolved} resolved')
        if ambiguous:
            parts.append(f'{ambiguous} ambiguous')
        if not_found:
            parts.append(f'{not_found} not found')
        return ' · '.join(parts) if parts else None

    @staticmethod
    def _orient_analyze_result(*, available: bool, content: str) -> str | None:
        if not available:
            return 'unavailable'
        if not content.strip():
            return 'no output'
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        if not lines:
            return None
        # Extract metric based on common payload patterns
        body = '\n'.join(lines[:20])
        body_lower = body.lower()
        if 'callers' in body_lower or 'caller of' in body_lower:
            # Count callers
            caller_lines = [line for line in lines if '::' in line or ' -> ' in line or '  ' in line and '(' in line and ')' in line]
            return f'{len(caller_lines)} callers' if caller_lines else 'completed'
        if 'dependency' in body_lower or 'depend on' in body_lower or 'import' in body_lower:
            dep_count = sum(1 for line in lines if line.strip() and ('<-' in line or '->' in line or 'import' in line.lower()))
            return f'{dep_count} deps' if dep_count else 'completed'
        if 'symbol' in body_lower:
            symbol_lines = [line for line in lines if line.strip() and not line.startswith('#') and not line.startswith('//')]
            return f'{len(symbol_lines)} symbols' if symbol_lines else 'completed'
        if 'tree' in body_lower or 'file_outline' in body_lower or 'recent' in body_lower:
            return 'completed'
        if 'semantic_search' in body_lower:
            return 'completed'
        return 'completed'

    def _render_server_ready_observation(self, obs: ServerReadyObservation) -> None:
        self._flush_pending_tool_cards()
        url = getattr(obs, 'url', '')
        port = getattr(obs, 'port', '')
        label = url or f'port {port}'
        self._append_history(
            format_activity_result_secondary(
                f'server ready · {label}',
                kind='ok',
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
        self,
        obs: RecallFailureObservation,
    ) -> None:
        self._flush_pending_tool_cards()
        error_msg = getattr(obs, 'error_message', '')
        recall_type = getattr(obs, 'recall_type', None)
        label = str(recall_type.value) if recall_type else 'recall'
        if error_msg:
            self._append_history(
                format_activity_result_secondary(
                    f'{label} failed · {error_msg}',
                    kind='err',
                )
            )

    def _render_file_download_observation(
        self,
        obs: FileDownloadObservation,
    ) -> None:
        self._flush_pending_tool_cards()
        path = getattr(obs, 'file_path', '')
        self._append_history(
            format_activity_result_secondary(
                f'downloaded · {path}',
                kind='neutral',
            ),
        )

    def _render_delegate_task_observation(
        self,
        obs: DelegateTaskObservation,
    ) -> None:
        self._stop_reasoning()
        pending = cast(Any, self._take_pending_activity_card('delegate'))
        workers_data = getattr(self, '_delegate_workers', {}) or {}
        result_message, result_kind, extra_lines = _summarize_delegate_observation(
            obs,
            workers_data=workers_data,
        )
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
        self,
        obs: TaskTrackingObservation,
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
        self,
        obs: AgentCondensationObservation,
    ) -> None:
        del obs


__all__ = ['ObservationRenderersMixin']
