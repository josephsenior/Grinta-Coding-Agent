"""Slash-command handlers shared by TUI and non-interactive CLI.

The host class (TUI screen or test double) must provide attributes and helpers
listed below. Command bodies live in sibling ``slash_command_*`` modules.

* attributes: ``_renderer``, ``_console``, ``_config``, ``_hud``,
  ``_controller``, ``_event_stream``, ``_next_action``, ``_pending_resume``,
  ``_last_user_message``;
* helper methods: ``_warn``, ``_usage``, ``_reject_extra_args``,
  ``_command_project_root``.

The actual command bodies live in sibling modules
(``_slash_command_dispatch``, ``_slash_command_checkpoint``,
``_slash_command_diff``, ``_slash_command_status``,
``_slash_command_actions``). This file is intentionally a thin mixin:

* one-line forwarders to the module functions;
* ``@staticmethod``s for ``_format_checkpoint_entry`` and
  ``_compute_checkpoint_diff_text`` (tests invoke them as class-level
  static methods).
"""

from __future__ import annotations

import subprocess  # noqa: F401  -- kept for test patch path ``patch('subprocess.run', ...)``
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from backend.cli._typing import SlashCommandsHost

if TYPE_CHECKING:
    from rich.console import Console

    from backend.core.config import AppConfig


class SlashCommandsMixin:
    """Mixin providing the slash-command surface of the REPL."""

    # Attributes provided by the concrete ``backend.cli.repl.Repl`` host class.
    # Declared here so the mixin's references type-check without forcing each
    # call site to carry an ``# type: ignore[attr-defined]``.
    if TYPE_CHECKING:
        _renderer: Any | None
        _console: Console
        _config: AppConfig
        _hud: Any
        _controller: Any | None
        _event_stream: Any | None
        _next_action: Any | None
        _pending_resume: str | None
        _last_user_message: str | None

        def _warn(self, msg: str) -> None: ...
        def _usage(self, name: str) -> str: ...
        def _reject_extra_args(self, parsed: Any) -> bool: ...
        def _command_project_root(self) -> Path: ...

    # -- checkpoint inspection (static methods kept on the class for tests) -

    @staticmethod
    def _format_checkpoint_entry(e: dict[str, Any]) -> str:
        from datetime import datetime as _dt

        ts = e.get('timestamp', 0)
        try:
            ts_str = _dt.fromtimestamp(float(ts)).strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            ts_str = str(ts)
        return (
            f'  {e.get("id", "?")[:12]:<12} {ts_str}  '
            f'{e.get("checkpoint_type", "?"):<18} {e.get("description", "")[:60]}'
        )

    @staticmethod
    def _compute_checkpoint_diff_text(
        sha: Any,
        workspace_path: Any,
    ) -> str:
        if not sha:
            return (
                '(checkpoint has no git commit; file-snapshot diff is not implemented '
                'in the CLI — use checkpoint(revert) to roll back instead).'
            )
        import subprocess as _sp

        try:
            proc = _sp.run(
                ['git', 'diff', str(sha)],
                cwd=str(workspace_path),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            return proc.stdout or proc.stderr or '(empty diff)'
        except Exception as exc:
            return f'(git diff failed: {exc})'

    # -- checkpoint forwarders ---------------------------------------------

    def _resolve_rollback_manager(self):
        import backend.cli.repl.slash_command_checkpoint as _ckpt

        return _ckpt.resolve_rollback_manager(self)

    def _parse_checkpoint_limit(self, args: list[str]) -> int | None:
        import backend.cli.repl.slash_command_checkpoint as _ckpt

        return _ckpt.parse_checkpoint_limit(self, args)

    def _notify_no_rollback_manager(self, message: str) -> None:
        import backend.cli.repl.slash_command_checkpoint as _ckpt

        return _ckpt.notify_no_rollback_manager(self, message)

    def _find_checkpoint_match(
        self,
        manager: Any,
        cp_id: str,
    ) -> dict[str, Any] | None:
        import backend.cli.repl.slash_command_checkpoint as _ckpt

        return _ckpt.find_checkpoint_match(self, manager, cp_id)

    def _handle_checkpoint_list(self, args: list[str]) -> None:
        import backend.cli.repl.slash_command_checkpoint as _ckpt

        return _ckpt.handle_checkpoint_list(self, args)

    def _handle_checkpoint_diff(self, args: list[str]) -> None:
        import backend.cli.repl.slash_command_checkpoint as _ckpt

        return _ckpt.handle_checkpoint_diff(self, args)

    # -- dispatch forwarders -----------------------------------------------

    def _handle_command(self, text: str) -> bool:
        import backend.cli.repl.slash_command_dispatch as _dispatch

        return _dispatch.handle_command(self, text)

    def _handle_parsed_command(self, parsed: Any) -> bool:
        import backend.cli.repl.slash_command_dispatch as _dispatch

        return _dispatch.handle_parsed_command(self, parsed)

    def _render_unknown_command(self, raw_cmd: str) -> None:
        import backend.cli.repl.slash_command_dispatch as _dispatch

        return _dispatch.render_unknown_command(self, raw_cmd)

    # -- autonomy forwarders -----------------------------------------------

    def _handle_autonomy_command(self, parsed: Any) -> None:
        import backend.cli.repl.slash_command_status as _status

        return _status.handle_autonomy_command(self, parsed)

    def _show_current_autonomy(self, valid_levels: tuple[str, ...]) -> None:
        import backend.cli.repl.slash_command_status as _status

        return _status.show_current_autonomy(self, valid_levels)

    def _apply_autonomy_level(self, new_level: str) -> None:
        import backend.cli.repl.slash_command_status as _status

        return _status.apply_autonomy_level(self, new_level)

    def _get_current_autonomy(self) -> str:
        import backend.cli.repl.slash_command_status as _status

        return _status.get_current_autonomy(self)

    # -- status forwarders --------------------------------------------------

    def _build_status_diagnostics(self) -> str:
        import backend.cli.repl.slash_command_status as _status

        return _status.build_status_diagnostics(self)

    def _cmd_status(self, parsed: Any) -> bool:
        import backend.cli.repl.slash_command_status as _status

        return _status.cmd_status(self, parsed)

    def _cmd_cost(self, parsed: Any) -> bool:
        import backend.cli.repl.slash_command_status as _status

        return _status.cmd_cost(self, parsed)

    def _cmd_health(self, parsed: Any) -> bool:
        import backend.cli.repl.slash_command_status as _status

        return _status.cmd_health(self, parsed)

    def _cmd_autonomy(self, parsed: Any) -> bool:
        import backend.cli.repl.slash_command_status as _status

        return _status.cmd_autonomy(self, parsed)

    def _cmd_mode(self, parsed: Any) -> bool:
        import backend.cli.repl.slash_command_status as _status

        return _status.cmd_mode(self, parsed)

    # -- diff forwarders ---------------------------------------------------

    def _parse_diff_args(
        self,
        parsed: Any,
    ) -> tuple[str, list[str]] | None:
        import backend.cli.repl.slash_command_diff as _diff

        return _diff.parse_diff_args(cast(SlashCommandsHost, self), parsed)

    def _build_diff_git_args(self, mode: str, paths: list[str]) -> list[str]:
        import backend.cli.repl.slash_command_diff as _diff

        return _diff.build_diff_git_args(mode, paths)

    def _run_git_diff(self, git_args: list[str], cwd: Path) -> str | None:
        import backend.cli.repl.slash_command_diff as _diff

        return _diff.run_git_diff(cast(SlashCommandsHost, self), git_args, cwd)

    @staticmethod
    def _parse_diff_files(diff_body: str) -> list[dict]:
        import backend.cli.repl.slash_command_diff as _diff

        return _diff.parse_diff_files(diff_body)

    def _renderer_render_diff(self, renderer: Any, diff_body: str) -> None:
        import backend.cli.repl.slash_command_diff as _diff

        return _diff.renderer_render_diff(self, renderer, diff_body)

    def _cmd_diff(self, parsed: Any) -> bool:
        import backend.cli.repl.slash_command_diff as _diff

        return _diff.cmd_diff(cast(SlashCommandsHost, self), parsed)

    # -- action forwarders -------------------------------------------------

    def _cmd_exit(self, parsed: Any) -> bool:
        import backend.cli.repl.slash_command_actions as _actions

        return _actions.cmd_exit(self, parsed)

    def _cmd_settings(self, parsed: Any) -> bool:
        import backend.cli.repl.slash_command_actions as _actions

        return _actions.cmd_settings(self, parsed)

    def _cmd_clear(self, parsed: Any) -> bool:
        import backend.cli.repl.slash_command_actions as _actions

        return _actions.cmd_clear(self, parsed)

    def _cmd_sessions(self, parsed: Any) -> bool:
        import backend.cli.repl.slash_command_actions as _actions

        return _actions.cmd_sessions(self, parsed)

    def _cmd_resume(self, parsed: Any) -> bool:
        import backend.cli.repl.slash_command_actions as _actions

        return _actions.cmd_resume(self, parsed)

    def _cmd_model(self, parsed: Any) -> bool:
        import backend.cli.repl.slash_command_actions as _actions

        return _actions.cmd_model(self, parsed)

    def _cmd_compact(self, parsed: Any) -> bool:
        import backend.cli.repl.slash_command_actions as _actions

        return _actions.cmd_compact(self, parsed)

    def _cmd_retry(self, parsed: Any) -> bool:
        import backend.cli.repl.slash_command_actions as _actions

        return _actions.cmd_retry(self, parsed)

    def _cmd_playbook_passthrough(self, parsed: Any) -> bool:
        import backend.cli.repl.slash_command_actions as _actions

        return _actions.cmd_playbook_passthrough(self, parsed)

    def _cmd_copy(self, parsed: Any) -> bool:
        import backend.cli.repl.slash_command_actions as _actions

        return _actions.cmd_copy(self, parsed)

    def _cmd_search(self, parsed: Any) -> bool:
        import backend.cli.repl.slash_command_actions as _actions

        return _actions.cmd_search(self, parsed)

    def _cmd_help(self, parsed: Any) -> bool:
        import backend.cli.repl.slash_command_actions as _actions

        return _actions.cmd_help(self, parsed)

    def _cmd_checkpoint(self, parsed: Any) -> bool:
        args = list(parsed.args)
        sub = args[0].lower() if args else ''
        if sub in {'list', 'ls'}:
            self._handle_checkpoint_list(args[1:])
            return True
        if sub == 'diff':
            self._handle_checkpoint_diff(args[1:])
            return True
        from backend.ledger.action import MessageAction

        label = ' '.join(args).strip()
        instruction = (
            'Use the `checkpoint` tool now to snapshot the current workspace state.'
        )
        if label:
            instruction += f' Use this label: {label}'
        self._next_action = MessageAction(content=instruction)
        if self._renderer is not None:
            self._renderer.add_system_message(
                f'Checkpoint queued{(" (" + label + ")") if label else ""}.',
                title='checkpoint',
            )
        return True
