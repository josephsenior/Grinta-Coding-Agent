"""Action renderers — shell domain."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.cli._typing import ActionRenderersHost

    _ActionRenderersBase = ActionRenderersHost
else:
    _ActionRenderersBase = object


from backend.cli._typing import ActionRenderersHost
from backend.cli.display.layout_tokens import (
    ACTIVITY_CARD_TITLE_SHELL,
)
from backend.cli.display.tool_call_display import tool_headline
from backend.cli.event_rendering.text_utils import (
    sync_reasoning_after_tool_line as _sync_reasoning_after_tool_line,
)
from backend.ledger.action import (  # noqa: E402
    CmdRunAction,
)


class _ActionShellMixin(_ActionRenderersBase):
    def _render_cmd_run_action(self, action: CmdRunAction) -> None:
        self._flush_pending_activity_card()
        if getattr(action, 'hidden', False):
            self.refresh()
            return
        if self._pending_shell_action is not None:
            self._flush_pending_shell_action()
        display_label = (getattr(action, 'display_label', '') or '').strip()
        if display_label:
            self._buffer_internal_shell_command(action, display_label)
            return
        self._buffer_external_shell_command(action)

    def _buffer_external_shell_command(self, action: CmdRunAction) -> None:
        self._pending_shell_is_internal = False
        self._pending_shell_title = None
        cmd_display = (action.command or '').strip()
        if len(cmd_display) > 12_000:
            cmd_display = cmd_display[:11_997] + '…'
        self._pending_shell_command = cmd_display
        label = f'$ {cmd_display}' if cmd_display else '$ (empty)'
        self._pending_shell_action = ('Ran', label)
        thought = getattr(action, 'thought', '') or ''
        _sync_reasoning_after_tool_line(self._reasoning, label, thought)
        self.refresh()

    def _buffer_internal_shell_command(
        self, action: CmdRunAction, display_label: str
    ) -> None:
        """Buffer an internal-tool ``CmdRunAction`` (``display_label`` set)."""
        meta = getattr(action, 'tool_call_metadata', None)
        function_name = getattr(meta, 'function_name', '') or ''
        _icon, headline = tool_headline(function_name, use_icons=self._cli_tool_icons)
        self._pending_shell_command = None
        self._pending_shell_action = ('Ran', display_label)
        self._pending_shell_title = headline or ACTIVITY_CARD_TITLE_SHELL
        self._pending_shell_is_internal = True
        self.refresh()
