"""Action renderers — terminal domain."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.cli._typing import ActionRenderersHost

    _ActionRenderersBase = ActionRenderersHost
else:
    _ActionRenderersBase = object


from backend.cli._typing import ActionRenderersHost
from backend.cli.display.layout_tokens import (
    ACTIVITY_CARD_TITLE_TERMINAL,
)
from backend.cli.event_rendering.text_utils import (
    sync_reasoning_after_tool_line as _sync_reasoning_after_tool_line,
)
from backend.ledger.action import (  # noqa: E402
    TerminalCloseAction,
    TerminalInputAction,
    TerminalReadAction,
    TerminalRunAction,
)


class _ActionTerminalMixin(_ActionRenderersBase):
    def _render_terminal_run_action(self, action: TerminalRunAction) -> None:
        self._flush_pending_tool_cards()
        cmd = (getattr(action, 'command', '') or '').strip()
        if len(cmd) > 12_000:
            cmd = cmd[:11_997] + '…'
        self._pending_shell_command = cmd
        label = cmd if cmd else '(empty)'
        self._print_activity(
            'Launch',
            f'$ {label}',
            None,
            title=ACTIVITY_CARD_TITLE_TERMINAL,
            shell_rail=True,
            badge_label='terminal',
        )
        self._ensure_reasoning()
        pty_line = f'{ACTIVITY_CARD_TITLE_TERMINAL} · {label}'
        thought = getattr(action, 'thought', '') or ''
        _sync_reasoning_after_tool_line(self._reasoning, pty_line, thought)
        self.refresh()

    def _render_terminal_input_action(self, action: TerminalInputAction) -> None:
        self._flush_pending_tool_cards()
        sess = (getattr(action, 'session_id', '') or '').strip()
        inp = getattr(action, 'input', '') or ''
        ctrl = getattr(action, 'control', None)
        is_ctl = bool(getattr(action, 'is_control', False))
        inp_display, sent_for_echo = self._terminal_input_display(
            inp=inp, ctrl=ctrl, is_ctl=is_ctl
        )
        self._last_terminal_input_sent = sent_for_echo
        cmd_detail = f'[{sess}]  $ {inp_display}' if sess else f'$ {inp_display}'
        self._print_activity(
            'Run',
            cmd_detail,
            None,
            title=ACTIVITY_CARD_TITLE_TERMINAL,
            badge_label='terminal',
        )
        self._ensure_reasoning()
        line = self._terminal_input_reasoning_line(sess=sess, inp_display=inp_display)
        thought = getattr(action, 'thought', '') or ''
        _sync_reasoning_after_tool_line(self._reasoning, line, thought)
        self.refresh()

    @staticmethod
    def _terminal_input_display(
        *, inp: str, ctrl: Any, is_ctl: bool
    ) -> tuple[str, str]:
        if ctrl and str(ctrl).strip():
            return f'ctrl {ctrl}'[:60], ''
        if is_ctl and inp:
            return inp[:60] + ('…' if len(inp) > 60 else ''), ''
        return (
            inp[:60] + ('…' if len(inp) > 60 else ''),
            inp.strip().rstrip('\r\n'),
        )

    @staticmethod
    def _terminal_input_reasoning_line(*, sess: str, inp_display: str) -> str:
        if sess and inp_display:
            return f'{ACTIVITY_CARD_TITLE_TERMINAL} input · {sess} · {inp_display}'
        if sess:
            return f'{ACTIVITY_CARD_TITLE_TERMINAL} input · {sess}'
        return f'{ACTIVITY_CARD_TITLE_TERMINAL} input · {inp_display or "…"}'

    def _render_terminal_read_action(self, action: TerminalReadAction) -> None:
        # Read is a polling operation — don't clutter the transcript with a
        # full card; just keep the reasoning panel up-to-date.
        sess = (getattr(action, 'session_id', '') or '').strip()
        self._ensure_reasoning()
        line = (
            f'{ACTIVITY_CARD_TITLE_TERMINAL} read · {sess}'
            if sess
            else f'{ACTIVITY_CARD_TITLE_TERMINAL} read · …'
        )
        thought = getattr(action, 'thought', '') or ''
        _sync_reasoning_after_tool_line(self._reasoning, line, thought)
        self.refresh()

    def _render_terminal_close_action(self, action: TerminalCloseAction) -> None:
        # Close is a fast bookkeeping op — keep it lightweight in the
        # transcript (one reasoning line, no full activity card) so the
        # agent's release of a session doesn't drown the next command.
        sess = (getattr(action, 'session_id', '') or '').strip()
        self._ensure_reasoning()
        line = (
            f'{ACTIVITY_CARD_TITLE_TERMINAL} close · {sess}'
            if sess
            else f'{ACTIVITY_CARD_TITLE_TERMINAL} close'
        )
        thought = getattr(action, 'thought', '') or ''
        _sync_reasoning_after_tool_line(self._reasoning, line, thought)
        self.refresh()
